"""Sequential native review and captured-artifact controls over invented notes."""
import base64,copy,hashlib,io,json,os,subprocess,sys,tempfile,time,threading,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from test_native import fixture
from signelet.adapter import data_values
from signelet.session import ReviewSession,SessionOwner,encoded,read_regular,publish,replay_bundle,load_store

C1={'note_id':'very','source_offset':4,'target_offset':9}
C2={'note_id':'blue','source_offset':9,'target_offset':19}
def start(**kw):
    raw=fixture('The very blue blue boat.','The very very blue blue blue boat.',[('very',4,8),('blue',9,13)]).to_json_string().encode()
    return raw,ReviewSession.start(raw,'old','new',['very','blue'],**kw)

def typed_start():
    note_id='__signelet_generated_very_0'
    store=fixture('The very blue blue boat.','The very very blue blue blue boat.',[('very',4,8),('blue',9,13),(note_id,19,23)])
    doc=json.loads(store.to_json_string())
    for row,kind,value in zip(doc['annotationsets'][0]['data'],('Bool','Int','Int'),(True,1,9007199254740993)):
        row['value']={'@type':kind,'value':value}
    raw=json.dumps(doc,ensure_ascii=False).encode()
    return raw,ReviewSession.start(raw,'old','new',['very','blue',note_id])

class SessionTests(unittest.TestCase):
    def test_multiple_notes_close_open_undo_and_replay_exact_data(self):
        raw,s=start();original=load_store(raw);first=s.step(C1,s.revision)
        self.assertEqual(first.view()['payload']['counts']['review'],1)
        opened=ReviewSession.open(first.bytes());last=opened.step(C2,opened.revision)
        self.assertEqual(last.view()['status'],'complete');self.assertEqual(last.view()['assumptions'],2)
        again=replay_bundle(last.bundle());self.assertEqual(again.bytes(),last.bytes())
        for row,wanted in zip(again._report['rows'],([9,13],[19,23])):
            native=load_store(again._native.encode());note=native.annotation(row['output_note_id']);span=list(note.textselections())[0]
            self.assertEqual([span.begin(),span.end()],wanted);self.assertEqual(data_values(note),data_values(original.annotation(row['id'])))
            self.assertEqual(json.loads(native.annotation(row['id']).json()),json.loads(original.annotation(row['id']).json()))
        self.assertEqual(last.undo(last.revision).bytes(),first.bytes());self.assertEqual(base64.b64decode(json.loads(last.bytes())['input_base64']),raw)

    def test_explicit_native_bool_int_and_large_integer_survive_sequential_replay(self):
        raw,s=typed_start();s=s.step(C1,s.revision);s=ReviewSession.open(s.bytes());s=s.step(C2,s.revision)
        r=replay_bundle(s.bundle());native=load_store(r._native.encode())
        for row,expected in zip(r._report['rows'],(True,1,9007199254740993)):
            actual=data_values(native.annotation(row['output_note_id']))[0]['value']
            self.assertIs(type(actual),type(expected));self.assertEqual(actual,expected)
        original=load_store(raw)
        for row in r._report['rows']:self.assertEqual(json.loads(native.annotation(row['id']).json()),json.loads(original.annotation(row['id']).json()))
        # Even Python's True==1 must not permit a typed native-data mutation.
        with zipfile.ZipFile(io.BytesIO(s.bundle())) as z:files={n:z.read(n) for n in z.namelist()}
        doc=json.loads(files['store.stam.json']);doc['annotationsets'][0]['data'][0]['value']={'@type':'Int','value':1};files['store.stam.json']=json.dumps(doc,ensure_ascii=False).encode()
        manifest=json.loads(files['manifest.json']);manifest['files']['store.stam.json']=hashlib.sha256(files['store.stam.json']).hexdigest();files['manifest.json']=encoded(manifest)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name,value in files.items():z.writestr(name,value)
        with self.assertRaises(ValueError):replay_bundle(out.getvalue())

    def test_stale_typed_unoffered_order_and_unknown_never_commit(self):
        raw,s=start();first=s.step(C1,s.revision)
        for choice,revision in ((C2,s.revision),({**C2,'source_offset':True},first.revision),(C1,first.revision),({**C2,'target_offset':999},first.revision)):
            with self.assertRaises(ValueError):first.step(choice,revision)
        for key,value in [('implementation','old'),('input_sha256','0'*64),('journal',[{'choice':C1,'prior_revision':'0'*64}])]:
            doc=json.loads(first.bytes());doc[key]=value
            with self.assertRaises(ValueError):ReviewSession(doc)
        doc=json.loads(first.bytes());doc['context']['cell_limit']=True
        with self.assertRaises(ValueError):ReviewSession(doc)
        _,unknown=start(cell_limit=0);self.assertEqual(unknown.view()['payload']['counts']['unknown'],2)
        with self.assertRaises(ValueError):unknown.step(C1,unknown.revision)
        self.assertEqual(replay_bundle(unknown.bundle()).view()['status'],'review_required')

    def test_owned_durability_failure_retry_foreign_change_and_lock(self):
        raw,s=start()
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'session'
            with SessionOwner(directory,create=s) as owner:
                with self.assertRaises(ValueError):SessionOwner(directory)
                before=(directory/'session.json').read_bytes()
                with patch('signelet.session.os.replace',side_effect=OSError('late replace failure')):
                    with self.assertRaises(OSError):owner.apply('step',s.revision,C1)
                self.assertEqual((directory/'session.json').read_bytes(),before);self.assertEqual(owner.session.revision,s.revision)
                owner.apply('step',s.revision,C1)
                with self.assertRaises(ValueError):owner.apply('step',s.revision,C1)
            with SessionOwner(directory) as owner:
                self.assertEqual(owner.session.view()['assumptions'],1)
                saved=(directory/'session.json').read_bytes();(directory/'session.json').write_bytes(saved+b'\n')
                with self.assertRaises(ValueError):owner.apply('undo',owner.session.revision)
                self.assertEqual((directory/'session.json').read_bytes(),saved+b'\n')

    def test_foreign_change_during_staging_is_preserved(self):
        _,s=start()
        with tempfile.TemporaryDirectory() as tmp,SessionOwner(Path(tmp)/'session',create=s) as owner:
            path=owner.directory/'session.json';real=os.fsync
            def foreign(fd):real(fd);path.write_bytes(b'foreign editor bytes')
            with patch('signelet.session.os.fsync',foreign):
                with self.assertRaises(ValueError):owner.apply('step',s.revision,C1)
            self.assertEqual(path.read_bytes(),b'foreign editor bytes');self.assertEqual(owner.session.revision,s.revision)
            self.assertFalse(list(owner.directory.glob('.signelet-*')))

    def test_regular_descriptor_capture_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'input';p.write_bytes(b'original');real=os.fstat
            def replace(fd):
                info=real(fd);p.rename(root/'old');p.write_bytes(b'changed');return info
            # fstat twice is intentional: replace only before the first capture.
            called=[False]
            def race(fd):
                if not called[0]:called[0]=True;return replace(fd)
                return real(fd)
            with patch('signelet.session.os.fstat',race):self.assertEqual(read_regular(p,100),b'original')
            fifo=root/'fifo';os.mkfifo(fifo)
            with self.assertRaises(ValueError):read_regular(fifo,100)
            out=root/'out'
            with patch('signelet.session.os.fsync',side_effect=OSError('sync failure')):
                with self.assertRaises(OSError):publish(out,b'complete')
            self.assertFalse(out.exists());publish(out,b'complete')
            with self.assertRaises(FileExistsError):publish(out,b'changed')
            self.assertEqual(out.read_bytes(),b'complete');self.assertFalse(list(root.glob('.signelet-*')))

    def test_bundle_hash_typed_native_changes_and_member_refusal(self):
        _,s=start();s=s.step(C1,s.revision);s=s.step(C2,s.revision)
        with zipfile.ZipFile(io.BytesIO(s.bundle())) as z:files={n:z.read(n) for n in z.namelist()}
        for member in ('original.stam.json','store.stam.json','review-ledger.json'):
            changed=dict(files)
            if member=='store.stam.json':
                doc=json.loads(changed[member]);doc['resources'][0]['text']='tampered';changed[member]=encoded(doc)
            else:changed[member]+=b'corrupt'
            manifest=json.loads(changed['manifest.json']);manifest['files'][member]=hashlib.sha256(changed[member]).hexdigest();changed['manifest.json']=encoded(manifest)
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                for n,b in changed.items():z.writestr(n,b)
            with self.assertRaises((ValueError,RuntimeError)):replay_bundle(out.getvalue())
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('../escape',b'x')
        with self.assertRaises(ValueError):replay_bundle(out.getvalue())

    def test_rehashed_ledger_references_must_identify_the_actual_migrated_note(self):
        _,s=typed_start();s=s.step(C1,s.revision);s=s.step(C2,s.revision)
        with zipfile.ZipFile(io.BytesIO(s.bundle())) as z:original={n:z.read(n) for n in z.namelist()}
        report=json.loads(original['review-ledger.json']);row=report['rows'][0]
        alternatives=[name for name in row['native_outputs'] if name!=row['output_note_id']]
        # Other generated objects, another migrated note and the pivot are not this note.
        alternatives += [report['rows'][1]['output_note_id'],report['pivot_id']]
        for target in alternatives:
            files=dict(original);changed=copy.deepcopy(report);changed['rows'][0]['output_note_id']=target;files['review-ledger.json']=encoded(changed)
            manifest=json.loads(files['manifest.json']);manifest['files']['review-ledger.json']=hashlib.sha256(files['review-ledger.json']).hexdigest();files['manifest.json']=encoded(manifest)
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                for name,raw in files.items():z.writestr(name,raw)
            with self.subTest(target=target),self.assertRaises(ValueError):replay_bundle(out.getvalue())
        self.assertEqual(replay_bundle(s.bundle()).view()['status'],'complete')
        # A consistent bijection of generated annotations and references remains valid.
        files=dict(original);native=json.loads(files['store.stam.json']);renamed=copy.deepcopy(report)
        mapping={name:f'renamed-generated-{i}' for i,name in enumerate(name for row in report['rows'] for name in row.get('native_outputs',[]))}
        def rename(value):
            if type(value) is list:return [rename(item) for item in value]
            if type(value) is dict:return {key:mapping.get(item,item) if type(item) is str and ((key=='@id' and value.get('@type')=='Annotation') or (key=='annotation' and value.get('@type')=='AnnotationSelector')) else rename(item) for key,item in value.items()}
            return value
        for row in renamed['rows']:
            if 'native_outputs' in row:row['native_outputs']=[mapping[name] for name in row['native_outputs']]
            if 'output_note_id' in row:row['output_note_id']=mapping[row['output_note_id']]
        files['store.stam.json']=json.dumps(rename(native)).encode();files['review-ledger.json']=encoded(renamed)
        manifest=json.loads(files['manifest.json'])
        for name in ('store.stam.json','review-ledger.json'):manifest['files'][name]=hashlib.sha256(files[name]).hexdigest()
        files['manifest.json']=encoded(manifest);out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name,raw in files.items():z.writestr(name,raw)
        self.assertEqual(replay_bundle(out.getvalue()).view()['status'],'complete')

    def test_close_waits_for_inflight_native_save(self):
        _,s=start()
        with tempfile.TemporaryDirectory() as tmp:
            owner=SessionOwner(Path(tmp)/'session',create=s);entered=threading.Event();release=threading.Event();real=ReviewSession.step
            def wait(*args):entered.set();release.wait(3);return real(*args)
            result=[]
            with patch.object(ReviewSession,'step',wait):
                worker=threading.Thread(target=lambda:result.append(owner.apply('step',s.revision,C1)));worker.start();self.assertTrue(entered.wait(3))
                closer=threading.Thread(target=owner.close);closer.start();time.sleep(.02);self.assertIsNotNone(owner._fd)
                release.set();worker.join(3);closer.join(3)
            self.assertFalse(worker.is_alive());self.assertFalse(closer.is_alive());self.assertEqual(result[0]['assumptions'],1)
            with SessionOwner(Path(tmp)/'session') as reopened:self.assertEqual(reopened.session.view()['assumptions'],1)

    def test_actual_killed_writer_recovers_without_stale_lock_deletion(self):
        _,s=start()
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'session'
            with SessionOwner(directory,create=s):pass
            process=subprocess.Popen([sys.executable,'-m','signelet','session','serve',str(directory),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertIn('serving',process.stdout.readline())
                with self.assertRaises(ValueError):SessionOwner(directory)
                process.kill();process.wait(timeout=3)
                self.assertTrue((directory/'.owner.lock').exists())
                with SessionOwner(directory) as owner:owner.apply('step',s.revision,C1)
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=3)
                process.stdout.close();process.stderr.close()
