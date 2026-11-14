"""Bounded public-profile retrieval. No login, cookies, scripts or access bypass.

GitHub uses the existing pinned API transport. LinkedIn permits one fixed-host
HTTPS request; inaccessible public pages are reported rather than fabricated.
All returned content is untrusted. No submitted evidence goes to an AI provider.
"""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit
from . import github_fetcher as github
from .github_validator import validate_github_repository_or_profile_url,validate_github_repository_url

LINKEDIN_HOST='www.linkedin.com'
MAX_HTML=262144
MAX_TEXT=20000
_DNS_SLOT=threading.BoundedSemaphore(1)


def linkedin_url(url):
    if not isinstance(url,str) or len(url)>2048 or not url.isascii() or any(ord(c)<=32 or ord(c)==127 for c in url) or '%' in url or '\\' in url:raise ValueError('Use an HTTPS LinkedIn /in/profile URL.')
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc.lower() not in ('linkedin.com','www.linkedin.com','linkedin.com:443','www.linkedin.com:443') or p.query or p.fragment or not re.fullmatch('/in/[A-Za-z0-9_-]{1,100}/?',p.path):raise ValueError('Use an HTTPS LinkedIn /in/profile URL without query parameters.')
    return 'https://'+LINKEDIN_HOST+p.path.rstrip('/')


def supported(material):
    if material['category']=='github':return validate_github_repository_or_profile_url(material['url']) is None
    if material['category']=='linkedin':
        try:linkedin_url(material['url']);return True
        except ValueError:return False
    return False


def result(status,text='',references=()):
    if github._SECRET_TEXT.search(text):return {'status':'sensitive_content_skipped','text':'','references':list(references),'untrusted':True}
    return {'status':status,'text':text[:MAX_TEXT],'references':list(references),'untrusted':True}


def github_profile(url,budget=None):
    if validate_github_repository_or_profile_url(url) is not None:raise ValueError('Expected a GitHub profile URL.')
    owner=validate_github_repository_url(url.rstrip('/')+'/__profile_metadata__')['owner']
    base='/users/'+owner
    budget=budget if budget is not None else github._Budget(time.monotonic()+12)
    try:
        profile=github._json_request(base,64000,budget)
        if not isinstance(profile,dict) or str(profile.get('login','')).casefold()!=owner.casefold():return result('invalid_response')
        bio=profile.get('bio')
        texts=[bio] if isinstance(bio,str) and bio.strip() else []
        path=base+'/repos?type=owner&sort=pushed&direction=desc&per_page=3'
        repositories=github._json_request(path,128000,budget,list_response=True)
        if not isinstance(repositories,list) or len(repositories)>3:return result('invalid_response')
        allowance=getattr(budget,'profile_repositories_left',3)
        for repo in repositories:
            if allowance<=0:break
            if not isinstance(repo,dict) or repo.get('private') is not False or repo.get('fork') is not False or str(repo.get('owner',{}).get('login','')).casefold()!=owner.casefold():continue
            name=repo.get('name');description=repo.get('description');language=repo.get('language')
            if not isinstance(name,str):continue
            validate_github_repository_url('https://github.com/'+owner+'/'+name)
            fields=[v for v in (description,language) if isinstance(v,str) and v.strip()]
            if fields:
                texts.append('Public repository metadata (not proof of authorship or proficiency): '+name+'. '+'; '.join(fields));allowance-=1
        budget.profile_repositories_left=allowance
        text='\n'.join(texts)
        return result('retrieved' if text.strip() else 'no_public_text',text,['https://api.github.com'+base,'https://api.github.com'+path])
    except github._FetchError as error:return result(error.status)
    except (ValueError,TypeError,AttributeError):return result('invalid_response')


class LinkedInText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.ignore=0;self.ld=False;self.script=[];self.depth=0;self.capture=0;self.parts=[];self.structured=[];self.blocked=False
    def handle_starttag(self,tag,attrs):
        if tag in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):return
        a=dict(attrs);self.depth+=1
        if tag in ('script','style','noscript','template'):
            self.ignore+=1
            if tag=='script' and a.get('type')=='application/ld+json':self.ld=True;self.script=[]
        if tag=='form' and any(v in a.get('action','').lower() for v in ('login','authwall','checkpoint')):self.blocked=True
        classes=a.get('class','').lower()
        if not self.ignore and not self.capture and any(v in classes for v in ('summary','experience','education','skills','headline')):self.capture=self.depth
    def handle_endtag(self,tag):
        if tag=='script' and self.ld:
            self.ld=False
            try:
                data=json.loads(''.join(self.script))
                def collect(value,depth=0):
                    if depth>8:return
                    if isinstance(value,list):
                        for item in value[:50]:collect(item,depth+1)
                    elif isinstance(value,dict):
                        types=value.get('@type',[]);types=[types] if isinstance(types,str) else types
                        if isinstance(types,list) and 'Person' in types:
                            for key in ('description','jobTitle','knowsAbout'):
                                field=value.get(key)
                                if isinstance(field,str):self.structured.append(field)
                                elif isinstance(field,list):self.structured.extend(v for v in field[:50] if isinstance(v,str))
                        for key in ('@graph','mainEntity'):collect(value.get(key),depth+1)
                collect(data)
            except (ValueError,RecursionError):pass
        if tag in ('script','style','noscript','template'):self.ignore=max(0,self.ignore-1)
        if self.capture==self.depth:self.capture=0
        self.depth=max(0,self.depth-1)
    def handle_data(self,data):
        if self.ld:
            if sum(map(len,self.script))+len(data)<=64000:self.script.append(data)
        elif not self.ignore and self.capture and data.strip():self.parts.append(data.strip())


def _linkedin_address(timeout):
    if not _DNS_SLOT.acquire(blocking=False):raise TimeoutError
    done=threading.Event();values=[]
    def resolve():
        try:values.extend(socket.getaddrinfo(LINKEDIN_HOST,443,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP))
        except OSError:pass
        finally:_DNS_SLOT.release();done.set()
    threading.Thread(target=resolve,daemon=True).start()
    if not done.wait(timeout):raise TimeoutError
    if not values or len(values)>16:raise OSError
    for family,kind,proto,_,address in values:
        if family not in (socket.AF_INET,socket.AF_INET6) or '%' in address[0] or not ipaddress.ip_address(address[0]).is_global:raise OSError
    return values[0]


class _LinkedInConnection(http.client.HTTPSConnection):
    def __init__(self):super().__init__(LINKEDIN_HOST,443,timeout=3,context=ssl.create_default_context())
    def connect(self):
        family,kind,proto,_,address=_linkedin_address(3)
        raw=socket.socket(family,kind,proto)
        try:raw.settimeout(3);raw.connect(address);self.sock=self._context.wrap_socket(raw,server_hostname=LINKEDIN_HOST)
        except BaseException:raw.close();raise


def linkedin_profile(url,budget=None):
    canonical=linkedin_url(url);connection=_LinkedInConnection();response=None
    budget=budget if budget is not None else github._Budget(time.monotonic()+10)
    try:timeout=min(10,budget.remaining())
    except github._FetchError:return result('timeout')
    if budget.requests>=github.MAX_REQUESTS:return result('analysis_limit_reached')
    budget.requests+=1
    def abort():
        sock=connection.sock
        if sock is not None:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        connection.close()
    timer=threading.Timer(timeout,abort);timer.daemon=True;timer.start()
    end=time.monotonic()+timeout
    try:
        connection.request('GET',urlsplit(canonical).path,headers={'User-Agent':'RecruitiFi-public-evidence/1.0','Accept':'text/html','Accept-Encoding':'identity','Connection':'close'})
        response=connection.getresponse()
        if response.status in (401,403,429,999) or 300<=response.status<400:return result('profile_access_blocked')
        if response.status!=200:return result('profile_unavailable')
        if 'text/html' not in (github._header(response,'Content-Type') or '').lower() or (github._header(response,'Content-Encoding') or 'identity').lower()!='identity':return result('unsupported_content_type')
        length=github._header(response,'Content-Length')
        if length and (not length.isdigit() or int(length)>MAX_HTML):return result('response_too_large')
        chunks=[];size=0
        while time.monotonic()<end:
            chunk=response.read1(min(8192,MAX_HTML-size+1))
            if not chunk:break
            size+=len(chunk)
            budget.api_bytes+=len(chunk)
            if budget.api_bytes>github.MAX_API_BYTES:return result('analysis_limit_reached')
            if size>MAX_HTML:return result('response_too_large')
            chunks.append(chunk)
        else:return result('timeout')
        parser=LinkedInText();parser.feed(b''.join(chunks).decode('utf-8',errors='replace'));parser.close()
        if parser.blocked:return result('profile_access_blocked')
        text='\n'.join(parser.structured or parser.parts)
        if not text.strip():return result('profile_unreadable')
        return result('retrieved',text,[canonical])
    except github._FetchError as error:return result(error.status)
    except (OSError,http.client.HTTPException,TimeoutError):return result('profile_unavailable')
    finally:
        timer.cancel()
        if response is not None:response.close()
        connection.close()


def fetch_profile(material,*,budget=None):
    return github_profile(material['url'],budget) if material['category']=='github' else linkedin_profile(material['url'],budget)
