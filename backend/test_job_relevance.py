import unittest
from unittest.mock import Mock
from .evidence.job_relevance import score
from .evidence.embedding_client import EmbeddingServiceError


def vector(index):
    return [float(i==index) for i in range(384)]


class JobRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock()
        self.client.embed.side_effect=lambda texts,**_: [vector(0 if text.startswith('Python') else 1) for text in texts]
        self.evidence=[{'candidate_id':900001,'material_id':7,'text':'Python fabricated project'}]
        self.requirement=lambda identity,text,weight:{'skill_id':identity,'name':text,'text':text,'weight':weight}

    def test_model_vectors_and_job_weights_determine_score(self):
        requirements=[self.requirement(1,'Python',70),self.requirement(2,'Other',20)]
        result=score(900001,requirements,self.evidence,client=self.client)
        self.assertEqual(result['score'],77.8)
        self.assertEqual(result['requirements'][0]['material_id'],7)
        self.assertEqual(result['requirements'][1]['status'],'missing')
        other=score(900001,[self.requirement(2,'Other',70)],self.evidence,client=self.client)
        self.assertEqual(other['score'],0)

    def test_missing_evidence_and_claims_never_fabricate_scores(self):
        requirements=[self.requirement(2,'Other',70)]
        self.assertIsNone(score(900001,requirements,[],client=self.client)['score'])
        self.client.embed.assert_not_called()
        result=score(900001,requirements,self.evidence,claimed_skill_ids=[2],client=self.client)
        self.assertEqual(result['score'],0)
        self.assertEqual(result['requirements'][0]['status'],'claimed_only')

    def test_service_failure_and_bad_vectors_return_unavailable(self):
        self.client.check_ready.side_effect=EmbeddingServiceError('unavailable')
        result=score(900001,[self.requirement(1,'Python',70)],self.evidence,client=self.client)
        self.assertEqual((result['status'],result['score']),('unavailable',None))
        self.client.check_ready.side_effect=None
        self.client.embed.side_effect=lambda texts,**_: [[float('nan')]*384 for _ in texts]
        self.assertIsNone(score(900001,[self.requirement(1,'Python',70)],self.evidence,client=self.client)['score'])

    def test_cross_candidate_evidence_rejected_before_model(self):
        with self.assertRaises(ValueError):score(900002,[self.requirement(1,'Python',70)],self.evidence,client=self.client)
        self.client.check_ready.assert_not_called()
