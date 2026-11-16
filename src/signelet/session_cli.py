"""CLI adapters for the shared native review session owner."""
import argparse,json
from pathlib import Path
from importlib.metadata import version
from . import __version__
from .session import ReviewSession,SessionOwner,read_regular,publish,MAX_SESSION_BYTES,replay_bundle
from .adapter import MAX_STORE_BYTES


def main(argv):
    parser=argparse.ArgumentParser(prog='signelet session',
        description='Review notes with native recomputation and a saved journal of explicit assumptions.',
        epilog='Exit 0: all selected notes transferred, or a snapshot saved. Exit 1: valid result still needs review. Exit 2: refusal/error. Close a serving session before CLI writes.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    commands=parser.add_subparsers(dest='command',required=True)
    start=commands.add_parser('start',help='Create a new review from an inline native STAM store',
        description='Keep the original input unchanged and create a fresh session directory. Choices remain conditional assumptions.')
    start.add_argument('store',type=Path,help='Inline native STAM JSON containing both text resources')
    start.add_argument('--source',required=True,help='Original resource ID')
    start.add_argument('--target',required=True,help='Edited resource ID')
    start.add_argument('--note',action='append',required=True,help='Selected note ID; repeat for each note')
    start.add_argument('--directory',type=Path,required=True,help='New session directory; existing paths are refused')
    start.add_argument('--pin',action='append',default=[],metavar='OLD:NEW',help='Explicit prior character assumption in raw Unicode code points; repeat as needed')
    start.add_argument('--max-band',type=int,default=64,help='Per-segment alignment band limit (default: 64)')
    start.add_argument('--cell-limit',type=int,default=2000000,help='Alignment cell budget (default: 2000000); exhaustion remains unknown')
    replay=commands.add_parser('replay',help='Verify a native bundle and replay its assumptions',
        description='Check bounded bundle members, hashes, replayed choices and native outputs. This is not authentication or approval.')
    replay.add_argument('bundle',type=Path,help='Native ZIP bundle exported by this session implementation')
    replay.add_argument('--directory',type=Path,required=True,help='New verified session directory; never replaces an existing path')
    resume=commands.add_parser('resume',help='Reopen a saved session into a new directory',
        description='Replay the saved assumptions with the same implementation/native dependency. Use this for another project; the live browser opens only its current original/context.')
    resume.add_argument('journal',type=Path,help='Saved session JSON; includes original/edited text and note data')
    resume.add_argument('--directory',type=Path,required=True,help='New session directory; existing paths are refused')
    descriptions={
        'status':('Inspect the saved revision, notes and assumptions','Read the current revision before step or undo. Valid unresolved results exit 1.'),
        'step':('Accept one currently offered character choice','Use the exact current revision from status. Recompute every selected note from the original input with cumulative assumptions.'),
        'undo':('Remove the latest accepted assumption and recompute','Use the exact current revision from status. Original notes remain the recomputation source.'),
        'snapshot':('Save the current complete session JSON','Choose a fresh file path. Includes original/edited text and note data; save does not mean all notes transferred.'),
        'export':('Save a verified native ZIP bundle','Choose a fresh file path. Bundle includes texts, native store, ledger and journal; it can still require review.'),
        'serve':('Review this session in your local browser','Open the exact printed loopback URL yourself; no browser opens automatically. Ctrl-C stops this server. Reload saved state after interruption; a disconnected response does not imply rollback.')}
    for name in ('status','step','undo','snapshot','export','serve'):
        help_text,description=descriptions[name]
        p=commands.add_parser(name,help=help_text,description=description)
        p.add_argument('directory',type=Path,help='Existing saved session directory; close its server before CLI writes')
        if name in ('step','undo'):p.add_argument('--revision',required=True,help='Exact current revision from session status; stale revisions are refused')
        if name=='step':
            p.add_argument('--note',required=True,help='Note ID with a currently offered choice')
            p.add_argument('--source-offset',type=int,required=True,help='Original raw Unicode code-point offset')
            p.add_argument('--target-offset',type=int,required=True,help='Currently offered edited-text code-point offset')
        if name in ('export','snapshot'):p.add_argument('--output',required=True,type=Path,help='New destination file; never overwrites an existing path')
        if name=='serve':p.add_argument('--port',type=int,default=8768,help='Loopback port (default: 8768; 0 chooses an available port)')
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
            print(json.dumps({'url':server.origin,'directory':str(args.directory),'status':'serving','software_version':__version__,'stam_version':version('stam')}),flush=True)
            try:server.serve_forever()
            finally:server.server_close()
            return 0
        print(json.dumps(owner.session.view(),ensure_ascii=False,allow_nan=False))
        return 0 if owner.session.view()['status']=='complete' or args.command=='snapshot' else 1
