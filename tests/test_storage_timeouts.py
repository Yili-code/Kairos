from app.storage import FirestoreRepository
from app.models import Candidate


def test_candidate_rpc_calls_have_explicit_timeouts_without_hidden_read_retries():
    calls=[]
    class Snapshot:exists=False
    class Collection:
        def document(self,key):return self
        def get(self,**kwargs):calls.append(('get',kwargs));return Snapshot()
        def set(self,*args,**kwargs):calls.append(('set',kwargs))
        def create(self,*args,**kwargs):calls.append(('create',kwargs))
        def where(self,*args,**kwargs):return self
        def limit(self,*args):return self
        def stream(self,**kwargs):calls.append(('stream',kwargs));return []
    repo=FirestoreRepository.__new__(FirestoreRepository);repo.collection=Collection()
    candidate=Candidate('test','x','x','https://example.test/','','test')
    assert repo.get('test') is None
    repo.save(candidate);assert repo.create_if_absent(candidate)
    assert repo.find_by_status(['discovered'])==[]
    assert len(calls)==4
    assert all(kwargs['timeout'] in {5,10} and kwargs['retry'] is None for _,kwargs in calls)
