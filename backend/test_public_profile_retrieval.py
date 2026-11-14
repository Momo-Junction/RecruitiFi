"""Synthetic public profiles; all HTTP and DNS responses are mocked."""
import json
import socket
import unittest
from unittest.mock import patch,Mock
from .evidence import public_profiles as p,github_fetcher as g
from .test_github_fetcher import Connection,Response


class PublicProfileRetrievalTests(unittest.TestCase):
    def test_github_public_bio_and_owned_repo_metadata_need_no_description(self):
        calls=[];routes={'/users/Synthetic':Response({'login':'Synthetic','bio':'Synthetic Python developer','repos_url':'http://127.0.0.1/never-follow'}),
          '/users/Synthetic/repos?type=owner&sort=pushed&direction=desc&per_page=3':Response([
            {'name':'Example','owner':{'login':'Synthetic'},'private':False,'fork':False,'description':'Fabricated FastAPI services','language':'Python','html_url':'http://169.254.169.254/never'},
            {'name':'Private','owner':{'login':'Synthetic'},'private':True,'fork':False,'description':'Do not include'},
            {'name':'Fork','owner':{'login':'Synthetic'},'private':False,'fork':True,'description':'Do not attribute'}])}
        with patch.object(g,'_open_connection',side_effect=lambda _:Connection(routes,calls)):
            data=p.github_profile('https://github.com/Synthetic')
        self.assertEqual(data['status'],'retrieved')
        self.assertIn('FastAPI',data['text']);self.assertNotIn('Do not',data['text'])
        self.assertEqual(len(calls),2);self.assertTrue(all(c[1].startswith('/users/Synthetic') for c in calls))

    def response(self,body,status=200,headers=None):
        response=Response(raw=body,status=status,headers=headers or [('Content-Type','text/html'),('Content-Length',str(len(body)))])
        response.close=Mock()
        response.getheader=lambda name,default=None:next((v for k,v in response.headers if k.lower()==name.lower()),default)
        return response

    def fetch_linkedin(self,response):
        connection=Mock();connection.getresponse.return_value=response
        with patch.object(p,'_LinkedInConnection',return_value=connection):return p.linkedin_profile('https://www.linkedin.com/in/synthetic-only')

    def test_linkedin_public_professional_json_text(self):
        body=b'<html><script>ignore this executable text</script><script type="application/ld+json">'+json.dumps({'@type':'Person','name':'Do not embed identity','jobTitle':'Synthetic Python developer','description':'Fabricated REST APIs'}).encode()+b'</script></html>'
        data=self.fetch_linkedin(self.response(body))
        self.assertEqual(data['status'],'retrieved');self.assertIn('REST APIs',data['text']);self.assertNotIn('identity',data['text']);self.assertNotIn('executable',data['text'])

    def test_linkedin_access_controls_and_no_content_are_not_evidence(self):
        for status in (301,401,403,429,999):self.assertEqual(self.fetch_linkedin(self.response(b'Login',status))['status'],'profile_access_blocked')
        self.assertEqual(self.fetch_linkedin(self.response(b'<form action="/login">Join now</form>'))['status'],'profile_access_blocked')
        self.assertEqual(self.fetch_linkedin(self.response(b'<html>Marketing page</html>'))['status'],'profile_unreadable')
        self.assertEqual(self.fetch_linkedin(self.response(b'x'*(p.MAX_HTML+1)))['status'],'response_too_large')

    def test_linkedin_url_and_dns_restrictions(self):
        for url in ('http://www.linkedin.com/in/test','https://www.linkedin.com.evil.invalid/in/test','https://user:pass@www.linkedin.com/in/test','https://www.linkedin.com:8080/in/test','https://www.linkedin.com/in/test?redirect=foo','https://www.linkedin.com/in/test/extra','https://127.0.0.1/in/test'):
            with self.subTest(url=url),self.assertRaises(ValueError):p.linkedin_url(url)
        for numeric in ('127.0.0.1','10.0.0.1','169.254.169.254'):
            with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(numeric,443))]),self.assertRaises(OSError):p._linkedin_address(1)
