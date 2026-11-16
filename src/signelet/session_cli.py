"""CLI adapters for the shared native review session owner."""
import argparse,json
from pathlib import Path
from .session import ReviewSession,SessionOwner,read_regular,publish,MAX_SESSION_BYTES,replay_bundle
from .adapter import MAX_STORE_BYTES


def main(argv):
    parser=argparse.ArgumentParser(prog='signelet session');commands=parser.add_subparsers(dest='command',required=True)
    start=commands.add_parser('start');start.add_argument('store',type=Path);start.add_argument('--source',required=True);start.add_argument('--target',required=True);start.add_argument('--note',action='append',required=True);start.add_argument('--directory',type=Path,required=True);start.add_argument('--pin',action='append',default=[],metavar='OLD:NEW');start.add_argument('--max-band',type=int,default=64);start.add_argument('--cell-limit',type=int,default=2000000)
    replay=commands.add_parser('replay');replay.add_argument('bundle',type=Path);replay.add_argument('--directory',type=Path,required=True)
    resume=commands.add_parser('resume');resume.add_argument('journal',type=Path);resume.add_argument('--directory',type=Path,required=True)
    for name in ('status','step','undo','snapshot','export','serve'):
        p=commands.add_parser(name);p.add_argument('directory',type=Path)
        if name in ('step','undo'):p.add_argument('--revision',required=True)
        if name=='step':
            p.add_argument('--note',required=True);p.add_argument('--source-offset',type=int,required=True);p.add_argument('--target-offset',type=int,required=True)
        if name in ('export','snapshot'):p.add_argument('--output',required=True,type=Path)
        if name=='serve':p.add_argument('--port',type=int,default=8768)
    args=parser.parse_args(argv)
    created=None
    if args.command=='start':created=ReviewSession.start(read_regular(args.store,MAX_STORE_BYTES),args.source,args.target,args.note,pins=[tuple(int(v) for v in pair.split(':')) for pair in args.pin],max_band=args.max_band,cell_limit=args.cell_limit)
    if args.command=='replay':created=replay_bundle(read_regular(args.bundle,32*1024*1024))
    if args.command=='resume':created=ReviewSession.open(read_regular(args.journal,MAX_SESSION_BYTES))
    with SessionOwner(args.directory,create=created) as owner:
        if args.command=='step':owner.apply('step',args.revision,{'note_id':args.note,'source_offset':args.source_offset,'target_offset':args.target_offset})
        if args.command=='undo':owner.apply('undo',args.revision)
        if args.command in ('export','snapshot'):
            publish(args.output,owner.session.bundle() if args.command=='export' else owner.session.bytes())
        if args.command=='serve':
            from .session_server import make_server
            server=make_server(owner,args.port)
            print(json.dumps({'url':server.origin,'directory':str(args.directory),'status':'serving'}),flush=True)
            try:server.serve_forever()
            finally:server.server_close()
            return 0
        print(json.dumps(owner.session.view(),ensure_ascii=False,allow_nan=False))
        return 0 if owner.session.view()['status']=='complete' or args.command=='snapshot' else 1
