"""One replayable owner for sequential, explicitly assumed correspondences."""
import base64
import hashlib
import io
from importlib.metadata import version
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import zipfile

from .adapter import AnnotationStore, MAX_STORE_BYTES, MAX_NOTES, _inline, integrate, data_values
from .review import MODEL, _pins, _texts, build_payload, parse_decision, validate_decision, render_html

SCHEMA='signelet-review-session-v1'
MAX_SESSION_BYTES=8*1024*1024
MAX_STEPS=32
IMPLEMENTATION=hashlib.sha256(version('stam').encode()+b''.join(Path(__file__).with_name(name).read_bytes() for name in ('session.py','adapter.py','review.py','_alignment.py'))).hexdigest()


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def read_regular(path,maximum,*,allow_symlink=False):
    if not hasattr(os,'O_NONBLOCK'):raise ValueError('nonblocking file admission unavailable')
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|(0 if allow_symlink else getattr(os,'O_NOFOLLOW',0)))
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>maximum:raise ValueError('bounded regular nonsymlink file required')
        parts=[];size=0
        while size<=maximum:
            part=os.read(fd,min(65536,maximum+1-size))
            if not part:break
            parts.append(part);size+=len(part)
        after=os.fstat(fd)
        if size>maximum or size!=info.st_size or (after.st_size,after.st_mtime_ns)!=(info.st_size,info.st_mtime_ns):raise ValueError('file exceeded limit or changed while reading')
        return b''.join(parts)
    finally:os.close(fd)


def publish(path,raw,*,replace=False,before_replace=None):
    """Complete bytes only; replacement is reserved for the locked session owner."""
    path=Path(path);temporary=None;published=False
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.signelet-',delete=False) as f:
            temporary=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
        if replace:
            if before_replace is not None:before_replace()
            os.replace(temporary,path);temporary=None
        else:os.link(temporary,path)
        published=True
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError as error:
                try:print(json.dumps({'status':'complete_output_published' if published else 'publication_failed','warning':'owned_staging_cleanup_failed','staging':str(temporary),'detail':str(error)}),file=sys.stderr)
                except OSError:pass


def load_store(raw):
    if type(raw) is not bytes or len(raw)>MAX_STORE_BYTES:raise ValueError('inline store exceeds4MiB')
    document=parse_decision(raw);_inline(document)
    if type(document) is not dict or document.get('@type')!='AnnotationStore' or type(document.get('resources')) is not list or any(type(r) is not dict or type(r.get('text')) is not str for r in document['resources']):raise ValueError('inline native AnnotationStore required')
    try:return AnnotationStore(string=raw.decode('utf-8'),config={'use_include':False,'strip_temp_ids':False})
    except Exception as error:raise ValueError('invalid inline native STAM store: '+str(error)) from error


def context_for(store,context):
    keys={'source_id','target_id','note_ids','pins','max_band','cell_limit'}
    if type(context) is not dict or set(context)!=keys:raise ValueError('invalid session context fields')
    for name,maximum in (('max_band',64),('cell_limit',2000000)):
        if type(context[name]) is not int or not 0<=context[name]<=maximum:raise ValueError('invalid typed alignment limits')
    names=context['note_ids']
    if type(names) is not list or not 1<=len(names)<=MAX_NOTES or any(type(n) is not str or not n for n in names) or len(set(names))!=len(names):raise ValueError('unique bounded note IDs required')
    try:
        for name in names:store.annotation(name)
        old,new=_texts(store,context['source_id'],context['target_id'])
    except Exception as error:raise ValueError('invalid session resources or selected notes: '+str(error)) from error
    return {**context,'pins':_pins(context['pins'],old,new)}


class ReviewSession:
    """Detached journal; opening recomputes each choice under its actual prior pins."""
    @classmethod
    def start(cls,raw,source_id,target_id,note_ids,*,pins=(),max_band=64,cell_limit=2000000):
        return cls({'schema':SCHEMA,'model':MODEL,'implementation':IMPLEMENTATION,
                    'input_sha256':hashlib.sha256(raw).hexdigest(),'input_base64':base64.b64encode(raw).decode(),
                    'context':{'source_id':source_id,'target_id':target_id,'note_ids':list(note_ids),'pins':list(pins),'max_band':max_band,'cell_limit':cell_limit},'journal':[]})

    @classmethod
    def open(cls,raw):
        return cls(parse_decision(raw,max_bytes=MAX_SESSION_BYTES))

    def __init__(self,document):
        raw_document=encoded(document)
        if len(raw_document)>MAX_SESSION_BYTES:raise ValueError('session exceeds8MiB')
        doc=parse_decision(raw_document,max_bytes=MAX_SESSION_BYTES)
        if type(doc) is not dict or set(doc)!={'schema','model','implementation','input_sha256','input_base64','context','journal'} or doc['schema']!=SCHEMA or doc['model']!=MODEL or doc['implementation']!=IMPLEMENTATION:raise ValueError('unsupported or stale session implementation/model')
        if type(doc['input_base64']) is not str:raise ValueError('invalid source encoding')
        raw=base64.b64decode(doc['input_base64'],validate=True)
        if doc['input_sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('original source digest mismatch')
        store=load_store(raw);context=context_for(store,doc['context'])
        if encoded(context)!=encoded(doc['context']):raise ValueError('noncanonical session context')
        journal=doc['journal']
        if type(journal) is not list or len(journal)>MAX_STEPS:raise ValueError('session exceeds32 assumptions')
        prefix={**doc,'journal':[]};pins=context['pins']
        for entry in journal:
            if type(entry) is not dict or set(entry)!={'prior_revision','choice'} or entry['prior_revision']!=hashlib.sha256(encoded(prefix)).hexdigest():raise ValueError('stale or corrupt assumption order')
            decision_binding=build_payload(raw,store,{'rows':[],'counts':{}},context['source_id'],context['target_id'],context['note_ids'],pins,context['max_band'],context['cell_limit'])['binding']
            selected=validate_decision(raw,store,decision_binding|{'choice':entry['choice']})
            pins=selected['pins']
            # Each accepted stage must remain natively recomputable, not just individually plausible.
            integrate(store,**{**context,'pins':pins})
            prefix['journal'].append(entry)
        output,report=integrate(store,**{**context,'pins':pins})
        native=output.to_json_string()
        reopened=load_store(native.encode())
        for row in report['rows']:
            reopened.annotation(row['id'])
            if row['status']=='transposed':
                note=reopened.annotation(row['output_note_id']);selection=list(note.textselections())[0]
                if [selection.begin(),selection.end()]!=row['target'] or selection.text()!=row['exact'] or data_values(note)!=data_values(store.annotation(row['id'])):raise ValueError('native reopen differs from verified notes')
        self._document=doc;self._native=native;self._report=report
        self._payload=build_payload(raw,store,report,context['source_id'],context['target_id'],context['note_ids'],pins,context['max_band'],context['cell_limit'])

    @property
    def revision(self):return hashlib.sha256(self.bytes()).hexdigest()
    def bytes(self):return encoded(self._document)
    def view(self):
        return json.loads(encoded({'revision':self.revision,'assumptions':len(self._document['journal']),
            'status':self._report['status'],'payload':self._payload,'journal':self._document['journal'],
            'warning':'Assumptions are user choices, not ground truth. Agreement remains conditional on model and pins.'}))
    def step(self,choice,revision):
        if type(revision) is not str or revision!=self.revision:raise ValueError('stale session revision; reload current saved state')
        doc=json.loads(self.bytes());doc['journal'].append({'prior_revision':revision,'choice':choice})
        return ReviewSession(doc)
    def undo(self,revision):
        if revision!=self.revision:raise ValueError('stale session revision; reload current saved state')
        doc=json.loads(self.bytes())
        if not doc['journal']:raise ValueError('no accepted assumption to undo')
        doc['journal'].pop();return ReviewSession(doc)
    def bundle(self):
        files={'session.json':self.bytes(),'original.stam.json':base64.b64decode(self._document['input_base64']),
               'store.stam.json':self._native.encode(),'review-ledger.json':encoded(self._report),
               'review.html':render_html(self._payload).encode()}
        limits={'session.json':MAX_SESSION_BYTES,'original.stam.json':MAX_STORE_BYTES,'store.stam.json':MAX_STORE_BYTES,'review-ledger.json':4*1024*1024,'review.html':12*1024*1024}
        if any(len(raw)>limits[name] for name,raw in files.items()) or sum(map(len,files.values()))>32*1024*1024-65536:raise ValueError('delivery exceeds bounded replay limits')
        files['manifest.json']=encoded({'schema':'signelet-session-delivery-v1','revision':self.revision,'status':self._report['status'],
            'assumptions':len(self._document['journal']),'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}})
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,raw in files.items():z.writestr(name,raw)
        return out.getvalue()


class SessionOwner:
    """One kernel-locked directory; state changes become visible only after save."""
    def __init__(self,directory,*,create=None):
        import fcntl
        self.directory=Path(directory);self._fd=None;self._mutex=threading.RLock()
        fresh=create is not None
        if fresh:self.directory.mkdir()
        try:
            self._fd=os.open(self.directory/'.owner.lock',os.O_RDWR|os.O_CREAT|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0),0o600)
            if not stat.S_ISREG(os.fstat(self._fd).st_mode):raise ValueError('session ownership requires regular lock')
            try:fcntl.flock(self._fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise ValueError('review session is open in another process; close it before using this command') from error
            path=self.directory/'session.json'
            if fresh:publish(path,create.bytes())
            raw=read_regular(path,MAX_SESSION_BYTES);self.session=ReviewSession.open(raw);self._saved=hashlib.sha256(raw).hexdigest()
        except BaseException:
            if fresh and not (self.directory/'session.json').exists():
                # Only our just-created empty reservation is disposable.
                try:(self.directory/'.owner.lock').unlink();self.directory.rmdir()
                except OSError:pass
            self.close()
            raise
    def close(self):
        # Do not release process ownership while an accepted save is in flight.
        with self._mutex:
            if self._fd is not None:os.close(self._fd);self._fd=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def read_session(self):
        with self._mutex:
            if self._fd is None:raise ValueError('session owner closed')
            if hashlib.sha256(read_regular(self.directory/'session.json',MAX_SESSION_BYTES)).hexdigest()!=self._saved:raise ValueError('saved session changed outside this owner; close and reopen')
            return self.session
    def import_session(self,candidate,revision):
        return self.apply('import',revision,candidate)
    def apply(self,operation,revision,choice=None):
        with self._mutex:
            if self._fd is None:raise ValueError('session owner closed')
            path=self.directory/'session.json'
            if hashlib.sha256(read_regular(path,MAX_SESSION_BYTES)).hexdigest()!=self._saved:raise ValueError('saved session changed outside this owner; close and reopen')
            if revision!=self.session.revision:raise ValueError('stale session revision; reload current saved state')
            if operation=='import':
                if not isinstance(choice,ReviewSession):raise ValueError('verified session required')
                a=json.loads(self.session.bytes());b=json.loads(choice.bytes())
                if (a['input_sha256'],encoded(a['context']))!=(b['input_sha256'],encoded(b['context'])):raise ValueError('different original/context; resume in a separate session directory')
                next_session=choice
            elif operation=='step':next_session=self.session.step(choice,revision)
            elif operation=='undo':next_session=self.session.undo(revision)
            else:raise ValueError('unknown session operation')
            if hashlib.sha256(read_regular(path,MAX_SESSION_BYTES)).hexdigest()!=self._saved:raise ValueError('saved session changed during computation')
            def unchanged():
                if hashlib.sha256(read_regular(path,MAX_SESSION_BYTES)).hexdigest()!=self._saved:raise ValueError('saved session changed before publication; close and reopen')
            raw=next_session.bytes();publish(path,raw,replace=True,before_replace=unchanged)
            self.session=next_session;self._saved=hashlib.sha256(raw).hexdigest()
            return self.session.view()


def replay_bundle(raw):
    """Verify bounded delivery bytes and independently recompute the journal."""
    if type(raw) is not bytes or len(raw)>32*1024*1024:raise ValueError('bundle exceeds32MiB')
    limits={'session.json':MAX_SESSION_BYTES,'original.stam.json':MAX_STORE_BYTES,'store.stam.json':MAX_STORE_BYTES,
            'review-ledger.json':4*1024*1024,'review.html':12*1024*1024,'manifest.json':65536}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        if len(infos)!=len(limits) or {i.filename for i in infos}!=set(limits) or any(i.flag_bits&1 or i.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) or i.file_size>limits[i.filename] for i in infos) or sum(i.file_size for i in infos)>32*1024*1024:raise ValueError('unsupported, duplicate or oversized bundle members')
        files={}
        for info in infos:
            with z.open(info) as member:content=member.read(limits[info.filename]+1)
            if len(content)!=info.file_size:raise ValueError('inconsistent member size')
            files[info.filename]=content
    manifest=parse_decision(files['manifest.json'])
    session=ReviewSession.open(files['session.json'])
    expected={'schema':'signelet-session-delivery-v1','revision':session.revision,'status':session._report['status'],
        'assumptions':len(session._document['journal']),'files':{name:hashlib.sha256(content).hexdigest() for name,content in files.items() if name!='manifest.json'}}
    if encoded(manifest)!=encoded(expected):raise ValueError('bundle manifest differs from captured bytes or replay status')
    if files['original.stam.json']!=base64.b64decode(session._document['input_base64']):raise ValueError('bundle original differs from session')
    saved_report=parse_decision(files['review-ledger.json'])
    originals=load_store(files['original.stam.json'])
    expected_rows={row['id']:row for row in session._report['rows']}
    def normalized(raw,report):
        # One bijection is shared by the native graph AND its ledger references.
        original_ids={a.id() for a in originals.annotations()}
        prefix='__signelet_generated_'
        while any(name.startswith(prefix) for name in original_ids):prefix='_'+prefix
        if type(report) is not dict or type(report.get('rows')) is not list or len(report['rows'])!=len(expected_rows):raise ValueError('invalid ledger rows')
        replacements={};seen=set()
        for row in report['rows']:
            if type(row) is not dict or type(row.get('id')) is not str or row['id'] not in expected_rows or row['id'] in seen:raise ValueError('invalid ledger note identity')
            seen.add(row['id']);ids=row.get('native_outputs',[])
            if type(ids) is not list or any(type(name) is not str for name in ids) or len(ids)!=len(set(ids)) or len(ids)!=len(expected_rows[row['id']].get('native_outputs',[])) or any(name in original_ids or name in replacements for name in ids):raise ValueError('invalid generated annotation identities')
            if ids and row.get('output_note_id') not in ids:raise ValueError('missing generated target identity')
            for index,name in enumerate(ids):replacements[name]=f'{prefix}{row["id"]}_{index}'
        document=parse_decision(raw)
        native_ids={a['@id'] for a in document['annotations']}
        if not set(replacements)<=native_ids-original_ids or len(set(replacements.values()))!=len(replacements):raise ValueError('normalization requires a bijection of newly generated annotations only')
        native=load_store(raw)
        for row in report['rows']:
            if row.get('status')!='transposed':continue
            try:
                note=native.annotation(row['output_note_id']);target=json.loads(note.json())['target'];selections=list(note.textselections())
                expected_row=expected_rows[row['id']]
                if target.get('@type')!='TextSelector' or target.get('resource')!=session._document['context']['target_id'] or len(selections)!=1 or [selections[0].begin(),selections[0].end()]!=expected_row.get('target') or selections[0].text()!=expected_row.get('exact') or encoded(data_values(note))!=encoded(data_values(originals.annotation(row['id']))):
                    raise ValueError('ledger output_note_id does not identify the verified direct target note')
            except (KeyError,TypeError) as error:raise ValueError('invalid ledger output reference') from error
        def visit(value):
            if type(value) is list:return [visit(v) for v in value]
            if type(value) is dict:
                return {k:replacements.get(v,v) if type(v) is str and ((k=='@id' and value.get('@type')=='Annotation') or (k=='annotation' and value.get('@type')=='AnnotationSelector')) else visit(v) for k,v in value.items()}
            return value
        ledger=json.loads(encoded(report))
        for row in ledger['rows']:
            if 'native_outputs' in row:row['native_outputs']=[replacements[name] for name in row['native_outputs']]
            if 'output_note_id' in row:row['output_note_id']=replacements[row['output_note_id']]
        # The pivot is deterministic and remains an exact reference, never discarded.
        return visit(document),ledger
    saved_native,saved_ledger=normalized(files['store.stam.json'],saved_report)
    fresh_native,fresh_ledger=normalized(session._native.encode(),session._report)
    if encoded(saved_ledger)!=encoded(fresh_ledger):raise ValueError('saved diagnostic ledger references differ from replay')
    if encoded(saved_native)!=encoded(fresh_native):raise ValueError('native note/resource/data structure differs from fresh replay')
    if files['review.html']!=render_html(session._payload).encode():raise ValueError('offline review page differs from replay')
    return session
