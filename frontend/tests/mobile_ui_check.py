"""Optional real-browser UI regression check; requires installed Python Playwright.

Run with the local Vite server: python frontend/tests/mobile_ui_check.py
Every API request is mocked with fabricated data. No real profile data is used.
"""
import json
import re
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:5173'


def fixture(page):
    # Any request not handled by the page fixture must fail, never reach real APIs.
    page.context.route('**/api/**',lambda route:route.abort())
    candidate=dict(id=402,anonymous_code='Talent #402',full_name='Synthetic Talent',email='fixture@example.invalid',has_cv=True,has_portfolio=False,languages={'English':'B2'},needs_visa_sponsorship=False,skills=[])
    company=dict(id=1,name='Fictional Company',industry='IT',booth_number='A1',relocation_support=False,working_language='English',min_match_threshold=50,must_have_skills=[{'skill_id':1,'weight':70}],nice_to_have_skills=[{'skill_id':2,'weight':20}])
    job=dict(id=5001,company_id=1,company_name=company['name'],title='Fictional Python Developer',industry='it',industry_label='IT',description='Synthetic test position only.',active=True,**{k:company[k] for k in ('working_language','relocation_support','min_match_threshold','must_have_skills','nice_to_have_skills')})
    profile={'candidate':candidate,'materials':[dict(id=7,category='cv',title='CV & résumé',description='',skill_id=None,url=None,filename='fixture.pdf',content_type='application/pdf')]}
    match=dict(job_id=5001,company_id=1,candidate_id=402,anonymous_code='Talent #402',total_score=0,min_match_threshold=50,meets_threshold=False,dealbreakers_passed=True,dealbreaker_reasons=[],must_have_skills=[],nice_to_have_skills=[],profile_proof_points=0,improvement_hints=[])
    accounts=[dict(demo_account_id='talent-001',role='talent',candidate_id=402,display_name='Synthetic Talent',available=True),dict(demo_account_id='employer-001',role='employer',company_id=1,display_name='Fictional Company',available=True)]
    state={'swipes':[],'writes':[],'account':None,'fail_next':False,'unexpected':[]}
    def handler(route):
        request=route.request;path=urlsplit(request.url).path
        headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,PUT,DELETE,OPTIONS','Access-Control-Allow-Headers':'*','Content-Type':'application/json'}
        def respond(value,status=200):route.fulfill(status=status,headers=headers,body=json.dumps(value))
        if request.method=='OPTIONS':route.fulfill(status=204,headers=headers);return
        if path=='/api/evidence-session/config':return respond(dict(verified_login_required=True,password_free_demo=True))
        if path=='/api/evidence-session':
            if request.method=='POST':state['account']=json.loads(request.post_data)['account']
            return respond(dict(account_id=state['account'],role='employer' if state['account']=='employer-001' else 'talent',candidate_id=402,company_id=1,csrf='synthetic-csrf'))
        if path=='/api/demo/accounts':
            if state.get('fail_catalog'):return respond({},503)
            return respond(dict(accounts=accounts,candidate_count=1,company_count=1))
        if path=='/api/companies':return respond([company])
        if path=='/api/candidates':return respond([candidate])
        if path=='/api/skills':return respond([dict(id=1,name='Python',esco_uri='urn:synthetic:1',category='IT'),dict(id=2,name='React',esco_uri='urn:synthetic:2',category='IT')])
        if path=='/api/jobs/industries':return respond([dict(id='it',label='IT')])
        if path in ('/api/jobs','/api/companies/1/jobs'):return respond([job])
        if path in ('/api/candidates/402/job-matches','/api/jobs/5001/matches','/api/companies/1/matches'):return respond([match])
        if path=='/api/candidates/402/profile':return respond(profile)
        if path=='/api/candidates/402/skills':
            candidate['skills']=[dict(skill_id=i,evidence_tier='self_declared') for i in json.loads(request.post_data)]
            return respond(profile)
        if path=='/api/ai-matches/profiles/402':return respond(dict(status='not_analyzed',matches={},sources=[],public_profile_retrieval_enabled=True))
        if path=='/api/hiring-tasks':return respond([])
        if path.startswith('/api/notifications/'):
            return respond(dict(entries=[],unread_count=0))
        if path=='/api/swipes':
            if request.method=='PUT':
                value=json.loads(request.post_data)
                if state['fail_next']:state['fail_next']=False;return respond({'detail':'Temporary synthetic save failure.'},503)
                state['writes'].append(value);state['swipes']=[value]
                return respond(dict(**value,mutual_match=False))
            return respond(state['swipes'])
        if path.startswith('/api/swipes/') and request.method=='DELETE':state['swipes']=[];return respond({})
        state['unexpected'].append(path);respond({'detail':'Unexpected mocked endpoint'},404)
    page.route('**/api/**',handler)
    return state


def enter(page,employer=False):
    page.goto(BASE)
    page.get_by_role('button',name='Continue as Employer' if employer else 'Continue as Talent',exact=True).click()
    page.get_by_label('Demo account',exact=True).select_option('employer-001' if employer else 'talent-001')
    page.get_by_role('button',name='Enter Dashboard',exact=True).click()
    expect(page.locator('.swipe-body h3')).to_be_visible()
    expect(page.locator('.swipe-actions .swipe-like')).to_be_enabled()
    expect(page.get_by_role('button',name='Continue as Talent',exact=True)).to_have_count(0)


def gesture(page,horizontal):
    box=page.locator('.swipe-card').bounding_box()
    x=box['x']+box['width']*.4;y=box['y']+110
    client=page.context.new_cdp_session(page)
    client.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[dict(x=x,y=y)]))
    for d in (20,50,85,115):
        client.send('Input.dispatchTouchEvent',dict(type='touchMove',touchPoints=[dict(x=x+d if horizontal else x,y=y if horizontal else y-d)]))
    client.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]));client.detach()


def main():
    screenshots=Path(tempfile.mkdtemp(prefix='recruitifi-mobile-ui-'))
    print('Synthetic screenshots:',screenshots,flush=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport=dict(width=390,height=844),has_touch=True,is_mobile=True)
        page=context.new_page();state=fixture(page);state['fail_catalog']=True
        page.goto(BASE,wait_until='domcontentloaded')
        expect(page.get_by_role('alert')).to_contain_text('Could not load demo accounts')
        expect(page.locator('.app-loading')).to_have_count(0)
        state['fail_catalog']=False;page.get_by_role('button',name='Retry',exact=True).tap()
        expect(page.get_by_role('button',name='Continue as Talent',exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle');context.close();print('Failed-startup feedback and retry recovery: PASS',flush=True)
        for width in (320,390,768,1280):
            context=browser.new_context(viewport=dict(width=width,height=667 if width==320 else 844),has_touch=True,is_mobile=width<768)
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            state=fixture(page);enter(page)
            page.screenshot(path=str(screenshots/f'viewport-{width}.png'))
            assert page.locator('body').evaluate('(e)=>e.scrollWidth')<=width,'Horizontal overflow'
            assert page.get_by_text('Explore your workspace',exact=True).count()==0
            assert page.get_by_text('Espoo TalentMatch · Hackathon demo',exact=True).count()==0
            expect(page.get_by_role('heading',name='Your next opportunity starts with a match.',exact=True)).to_be_visible()
            status=page.get_by_label('Analysis status: Not analyzed',exact=True);status.tap()
            expect(page.get_by_text('Evidence comes first',exact=True)).to_be_visible()
            if width==390:page.screenshot(path=str(screenshots/'analysis-status-390.png'))
            status.tap()
            assert not state['writes'],'Status dropdown must not swipe'
            permission=page.locator('.consent-row').first
            permission.scroll_into_view_if_needed();
            if width<640:expect(page.locator('.swipe-actions')).not_to_have_class(re.compile('is-on-screen'))
            permission.tap();expect(permission.locator('input')).to_be_checked()
            a=permission.locator('input').bounding_box();b=permission.locator('span').bounding_box();assert abs(a['y']-b['y'])<=4
            bell=page.get_by_role('button',name='Notifications',exact=False);bell.tap()
            expect(bell).to_have_css('background-color','rgb(0, 80, 181)')
            page.locator('section[aria-label="Notifications"]').get_by_role('button',name='Close',exact=True).tap()
            select=page.get_by_label('Skill to add',exact=True)
            assert select.input_value()=='' and float(select.evaluate('(e)=>getComputedStyle(e).fontSize').replace('px',''))>=16
            select.select_option('2');page.get_by_role('button',name='Add skill',exact=True).tap();expect(page.get_by_role('button',name='Remove React',exact=True)).to_be_visible()
            like=page.locator('.swipe-actions .swipe-like');reject=page.locator('.swipe-actions .swipe-pass')
            like.scroll_into_view_if_needed();card=page.locator('.swipe-card').bounding_box();lb=like.bounding_box();rb=reject.bounding_box()
            assert abs((lb['x']+lb['width']/2+rb['x']+rb['width']/2)/2-(card['x']+card['width']/2))<3,'Reaction pair must be centered'
            page.screenshot(path=str(screenshots/f'talent-{width}.png'),full_page=True)
            state['fail_next']=True;like.tap();expect(page.get_by_role('alert')).to_contain_text('Temporary synthetic save failure')
            expect(like).to_be_enabled();like.tap();expect(page.get_by_text('Interested in Fictional Python Developer. Waiting for a response.',exact=True)).to_be_visible()
            assert len(state['writes'])==1 and state['writes'][-1]['decision']=='like'
            page.get_by_role('button',name='Undo last decision').tap();expect(reject).to_be_enabled();reject.tap()
            expect(page.get_by_text('Rejected Fictional Python Developer.',exact=True)).to_be_visible();assert state['writes'][-1]['decision']=='pass'
            page.get_by_role('button',name='Undo last decision').tap();expect(like).to_be_enabled()
            if width==390:
                page.locator('.swipe-card').scroll_into_view_if_needed();count=len(state['writes']);gesture(page,False);page.wait_for_timeout(250);assert len(state['writes'])==count,'Vertical scrolling must not swipe'
                page.locator('.swipe-card').scroll_into_view_if_needed();gesture(page,True)
                expect(page.get_by_text('Interested in Fictional Python Developer. Waiting for a response.',exact=True)).to_be_visible();assert len(state['writes'])==count+1
            assert not errors,errors;assert not state['unexpected'],state['unexpected']
            page.wait_for_load_state('networkidle');context.close();print(f'{width}px touch controls, failure recovery, alignment, status dropdown, notifications and skill selection: PASS',flush=True)
        context=browser.new_context(viewport=dict(width=390,height=844),has_touch=True,is_mobile=True,reduced_motion='reduce')
        page=context.new_page();page.add_init_script('window.matchMedia=undefined');state=fixture(page);enter(page,True)
        page.locator('.swipe-actions .swipe-like').tap();expect(page.get_by_text('Talent #402 added to your shortlist.',exact=True)).to_be_visible();assert state['writes'][-1]['actor']=='employer'
        page.wait_for_load_state('networkidle');context.close();browser.close()
        print('Employer touch action and missing matchMedia fallback: PASS')
    print('Synthetic screenshots:',screenshots)


if __name__=='__main__':main()
