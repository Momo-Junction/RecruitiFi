"""Model-backed evidence coverage calculation; no DB, consent or API side effects.

Callers must authorize supplied evidence before invoking this module. This module
does not turn demo account selection into authorization or publish private text.
"""
import math
import time

from .embedding_client import EmbeddingClient, EmbeddingServiceError, MODEL_ID, MODEL_REVISION

VERSION = 'weighted-semantic-coverage-v1'
LOW, HIGH = .20, .65


def score(candidate_id, requirements, fragments, *, claimed_skill_ids=(), client=None):
    """Requirements: skill_id/name/text/weight. Fragments: candidate_id/material_id/text.

    Score = 100 * sum(weight * clip((best_cosine-.20)/.45,0,1))/sum(weight).
    These are heuristic relevance anchors, NOT hiring probabilities or empirical
    validation of competence. Claimed skills without evidence contribute zero.
    """
    if type(candidate_id) is not int or candidate_id < 1:
        raise ValueError('Invalid candidate identity.')
    if not isinstance(requirements,list) or not 1 <= len(requirements) <= 100:
        raise ValueError('Supply 1–100 existing skill requirements.')
    seen=set()
    for requirement in requirements:
        identity=requirement['skill_id']; weight=requirement['weight']; text=requirement['text']
        if (type(identity) is not int or identity < 1 or identity in seen
                or type(weight) not in (int,float) or not math.isfinite(weight) or weight <= 0
                or not isinstance(text,str) or not text.strip() or len(text)>400):
            raise ValueError('Invalid or duplicate requirement.')
        seen.add(identity)
    if not isinstance(fragments,list) or len(fragments)>6:
        raise ValueError('At most six bounded attributed fragments are supported.')
    for fragment in fragments:
        if (fragment['candidate_id']!=candidate_id or type(fragment['material_id']) is not int
                or fragment['material_id']<1 or not isinstance(fragment['text'],str)
                or not fragment['text'].strip() or len(fragment['text'])>200):
            raise ValueError('Invalid or cross-candidate evidence.')
    base={'score':None,'version':VERSION,'model':MODEL_ID,'revision':MODEL_REVISION,'requirements':[]}
    if not fragments:
        return {**base,'status':'not_analyzed','reason':'missing_evidence'}
    deadline=time.monotonic()+120
    try:
        client=client if client is not None else EmbeddingClient()
        client.check_ready(deadline=deadline)
        texts=[r['text'] for r in requirements]+[f['text'] for f in fragments]
        vectors=[]
        for start in range(0,len(texts),3):
            if time.monotonic()>=deadline:raise EmbeddingServiceError('timeout')
            batch=client.embed(texts[start:start+3],deadline=deadline)
            if len(batch)!=len(texts[start:start+3]):raise EmbeddingServiceError('invalid_response')
            for vector in batch:
                if (len(vector)!=384 or any(type(n) not in (float,int) or not math.isfinite(n) for n in vector)
                        or abs(math.hypot(*vector)-1)>.001):
                    raise EmbeddingServiceError('invalid_response')
            vectors.extend(batch)
    except EmbeddingServiceError:
        return {**base,'status':'unavailable','reason':'model_unavailable'}
    evidence=vectors[len(requirements):]; findings=[]; total=0
    for requirement,vector in zip(requirements,vectors):
        similarities=[math.fsum(a*b for a,b in zip(vector,v))/(math.hypot(*vector)*math.hypot(*v)) for v in evidence]
        index=max(range(len(evidence)),key=lambda i: similarities[i])
        cosine=max(-1.,min(1.,similarities[index])); coverage=max(0.,min(1.,(cosine-LOW)/(HIGH-LOW)))
        supported=coverage>0
        findings.append({'skill_id':requirement['skill_id'],'skill_name':requirement['name'],
            'weight':requirement['weight'],'cosine':cosine,'coverage':coverage,
            'status':'supported' if supported else 'claimed_only' if requirement['skill_id'] in claimed_skill_ids else 'missing',
            'material_id':fragments[index]['material_id'] if supported else None,
            'excerpt':fragments[index]['text'][:160] if supported else None,
            'review_status':'unreviewed'})
        total+=requirement['weight']*coverage
    return {**base,'status':'completed','score':round(100*total/sum(r['weight'] for r in requirements),1),'requirements':findings}
