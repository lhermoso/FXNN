#!/usr/bin/env python3
"""Run only the preregistered economic research stage, in explicit durable phases."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fxnn import economic_research as research
from fxnn.economic_fit import phase_plan, slots
from fxnn.economic_lifecycle import Lifecycle, fingerprint, atomic_json


def read(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['development-data','reserve','development-models',
        'final-models','development-portfolios','development-report','freeze',
        'confirmation-data','confirmation-probabilities','confirmation-portfolios',
        'confirmation-report','replay-development','replay-confirmation','complete'])
    parser.add_argument('--config',type=Path,default=Path('configs/economic_ticks_v1.json'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preregistered-sha',required=True)
    parser.add_argument('--tzfile',default='/usr/share/zoneinfo/America/New_York')
    parser.add_argument('--curl-binary',default='/usr/bin/curl')
    parser.add_argument('--receipts',type=Path,help='JSON mapping of original receipt fingerprints')
    args=parser.parse_args(argv)
    repo=Path(__file__).resolve().parents[1]
    config=research.load_config(args.config)
    if args.config.resolve()!=(repo/'configs/economic_ticks_v1.json').resolve():
        raise ValueError('Use the registered repository config')
    research.verify_preregistration(repo,args.preregistered_sha)
    output=args.output.resolve()
    life=Lifecycle(config['global_ledger'])
    clock=research.clock_for(config)
    def progress(value):print(json.dumps(value,allow_nan=False),flush=True)
    def evidence(phase):return read(output/phase/'source-evidence.json')
    def matrix(phase):return research.load_window_data(output/phase,evidence(phase))
    def model_report(final=False):return read(output/('models-final' if final else 'models-development')/'report.json')
    def model_fp(final=False):
        name='FINAL_MODELS_VERIFIED' if final else 'DEVELOPMENT_VERIFIED'
        checks=[c for c in life.read()['checkpoints'] if c.get('phase')==name]
        if len(checks)!=1:raise ValueError('One authoritative model checkpoint required')
        return checks[0]['artifacts']['report']
    if args.phase=='development-data':
        result=research.make_development_data(repo,config,output/'development',args.preregistered_sha,progress)
    elif args.phase=='reserve':
        # All source labels must authenticate before consuming the single reservation.
        matrix('development')
        result=research.reserve_models(repo,config,args.preregistered_sha,tzfile=args.tzfile,
            curl_binary=args.curl_binary,slots=slots(phase_plan(config['folds']))).read()
        result={key:result[key] for key in ('S','guard','sealed')}
    elif args.phase in ('development-models','final-models'):
        final=args.phase=='final-models'
        result=research.model_segment(config,life,matrix('development'),clock,
            output/('models-final' if final else 'models-development'),final=final)
        if not final:
            operational=output/'operational-development.jsonl'
            if not operational.exists():
                try:research.operational_predictions(config,life,matrix('development'),clock,model_fp(),operational)
                except OSError:
                    life.poison('Development operational prediction persistence failed');raise
            research.verify_operational_predictions(config,life,matrix('development'),clock,
                                                   model_fp(),fingerprint(operational))
        result={'report':model_fp(final)}
    elif args.phase=='confirmation-data':
        result=research.make_confirmation_data(config,life,evidence('development'),output/'confirmation',progress)
    elif args.phase=='confirmation-probabilities':
        try:
            result=research.final_probabilities(config,life,matrix('confirmation'),model_fp(True),
                output/'probabilities-confirmation',fingerprint(output/'confirmation/source-evidence.json'))
        except OSError:
            # Observed persistence faults remain fail-closed. Process death and
            # KeyboardInterrupt leave canonical prediction intent recoverable.
            life.poison('Confirmation prediction persistence failed');raise
    elif args.phase in ('development-portfolios','confirmation-portfolios','replay-development','replay-confirmation'):
        confirmation=args.phase in ('confirmation-portfolios','replay-confirmation')
        phase='confirmation' if confirmation else 'development'
        replay=args.phase.startswith('replay-')
        if confirmation:
            predictions=fingerprint(output/'probabilities-confirmation/report.json')
            research.verify_final_probabilities(config,life,matrix(phase),model_fp(True),predictions,fingerprint(output/'confirmation/source-evidence.json'))
            operational=read(predictions['path'])['operational']
        else:
            operational=fingerprint(output/'operational-development.jsonl')
            research.verify_operational_predictions(config,life,matrix(phase),clock,model_fp(),operational)
        result=research.portfolio_segment(config,life,output/phase,evidence(phase),operational,
                                          output/('portfolios-'+phase),confirmation=confirmation,replay=replay)
        if not replay:atomic_json(output/('aggregate-'+phase+'.json'),result)
    elif args.phase in ('development-report','confirmation-report'):
        from fxnn.economic_report import build_report,write_report,markdown,aggregate_csv,sync_report_directory
        confirmation=args.phase=='confirmation-report'
        kwargs={}
        if confirmation:
            kwargs['confirmation']={'execution_status':'COMPLETED',
                                    'portfolios':read(output/'aggregate-confirmation.json')}
        report=build_report(model_report(),model_report(True),read(output/'aggregate-development.json'),
            artifacts={'development_models':model_fp(),'final_models':model_fp(True)},**kwargs)
        report_output=output/('report-confirmation' if confirmation else 'report-development')
        try:
            if report_output.exists():
                expected_files={'report.json':json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)+'\n',
                                'report.md':markdown(report),'aggregates.csv':aggregate_csv(report)}
                if any((report_output/name).read_bytes()!=text.encode('utf8') for name,text in expected_files.items()):
                    raise ValueError('Existing report differs from recomputed aggregates')
                sync_report_directory(report_output)
                result={name:fingerprint(report_output/name) for name in expected_files}
            else:result=write_report(report,report_output)
        except Exception:
            life.poison('Aggregate report publication failed');raise
    elif args.phase=='freeze':
        if args.receipts is None:raise ValueError('Original CI/review/dependency/validation receipts required')
        artifacts={name:fingerprint(output/path) for name,path in {
            'development_source':'development/source-evidence.json',
            'development_models':'models-development/report.json','final_models':'models-final/report.json',
            'development_portfolios':'portfolios-development/portfolio-manifest.json',
            'development_report':'report-development/report.json'}.items()}
        result=research.release_freeze(repo,config,life,args.preregistered_sha,read(args.receipts),artifacts)
    else:
        # Completion only follows independently verified, durable full-window artifacts.
        final_report=read(output/'report-confirmation/report.json')
        if final_report.get('confirmation',{}).get('execution_status')!='COMPLETED':
            raise ValueError('Full-window report required before lifecycle completion')
        research.verify_final_probabilities(config,life,matrix('confirmation'),model_fp(True),
                                            fingerprint(output/'probabilities-confirmation/report.json'),fingerprint(output/'confirmation/source-evidence.json'))
        verified_confirmation=research.portfolio_segment(config,life,output/'confirmation',evidence('confirmation'),
            read(output/'probabilities-confirmation/report.json')['operational'],
            output/'portfolios-confirmation',confirmation=True,replay=True)
        from fxnn.economic_report import build_report
        verified_development=research.portfolio_segment(config,life,output/'development',evidence('development'),
            fingerprint(output/'operational-development.jsonl'),output/'portfolios-development',replay=True)
        expected=build_report(model_report(),model_report(True),verified_development,
            confirmation={'execution_status':'COMPLETED','portfolios':verified_confirmation},
            artifacts={'development_models':model_fp(),'final_models':model_fp(True)})
        if final_report!=expected:
            raise ValueError('Final aggregate differs from verified portfolio replay')
        research.synchronize_report_for_transition(life,output/'report-confirmation')
        result={'report':fingerprint(output/'report-confirmation/report.json')}
        life.close('COMPLETED',result)
    progress(result)


if __name__=='__main__':main()
