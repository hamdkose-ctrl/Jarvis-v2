"""Opt-in loopback-only webhook receiver. Public HTTPS is external setup.

``/whatsapp/<owner>``: Meta WhatsApp webhook.
``/event/<owner>/<source>``: signed generic events (see ``event_webhooks``).
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import re
import threading
import sqlite3
from urllib.parse import urlsplit,parse_qs
from modules import event_webhooks, llm, message_inbox, service_store
from modules.publish_services import _record_failure

_LOCK=threading.Lock()
_SERVER=None


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass # verify_token in a query must never be logged

    def reply(self,code,body=b''):
        self.send_response(code);self.send_header('Content-Length',str(len(body)));self.send_header('Content-Type','text/plain');self.send_header('Connection','close');self.end_headers();self.wfile.write(body);self.close_connection=True

    def owner(self):
        parsed=urlsplit(self.path)
        match=re.fullmatch(r'/whatsapp/([\w-]{1,100})',parsed.path)
        if not match or len(self.path)>4096:raise ValueError('Webhook yolu geçersiz.')
        self.allowed(match[1])
        return match[1],parse_qs(parsed.query)

    def allowed(self,owner):
        allowed=getattr(self.server,'allowed_owners',None)
        if allowed is not None and owner not in (allowed() if callable(allowed) else allowed):raise PermissionError('Webhook kullanıcısı kayıtlı değil.')

    def body(self,limit):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:raise ValueError('Gövde uzunluğu geçersiz.')
        size=int(self.headers['Content-Length'])
        if not 0<size<=limit:raise OverflowError('Gövde çok büyük.')
        self.connection.settimeout(2)
        body=self.rfile.read(size)
        if len(body)!=size:raise ValueError('Gövde eksik.')
        return body

    def _gateway_event(self,owner,source,payload):
        """Dış kaynaktan gelen olayı canonical hook hattına bildirir; yük gönderilmez."""
        try:
            from modules import hooks
            hooks.observe('gateway',{'event':'inbound','source':str(source)[:40],
                                     'kind':str((payload or {}).get('kind') or '')[:40]},owner=owner)
        except Exception:
            _record_failure('modules/webhook_server.py:_gateway_event')

    def event_post(self,owner,source):
        token=llm._key_context.set(owner)
        try:
            self.allowed(owner)
            payload=event_webhooks.ingest(owner,source,self.body(event_webhooks.MAX_BODY),self.headers.get('X-Jarvis-Signature',''),
                                           self.headers.get('X-Jarvis-Timestamp',''))
            key='webhook:'+source
            try:
                from modules import runtime_subscription
                runtime_subscription.ensure_source(owner,key,goal='Olay webhook kaynağı: '+source,fresh_after=0.0)
                runtime_subscription.publish(owner,key,payload,kind='webhook_event')
            except Exception:
                _record_failure('modules/webhook_server.py:event_subscription')
            self._gateway_event(owner,source,payload or {})
            event_notify=getattr(self.server,'event_notify',None)
            if event_notify:
                try:event_notify(owner,{'source':key,'kind':'incoming','payload':payload})
                except Exception:
                    _record_failure('modules/webhook_server.py:event_notify')
            return self.reply(200,b'OK')
        except OverflowError:return self.reply(413)
        except (PermissionError,FileNotFoundError):return self.reply(403)
        except (ValueError,TypeError,KeyError,AttributeError):return self.reply(400)
        except (OSError,TimeoutError,sqlite3.Error):return self.reply(503)
        finally:llm._key_context.reset(token)

    def do_GET(self):
        token=None
        try:
            owner,query=self.owner();token=llm._key_context.set(owner)
            settings=message_inbox.config(owner)
            if query.get('hub.mode')!=['subscribe'] or len(query.get('hub.verify_token',[]))!=1 or not hmac.compare_digest(query['hub.verify_token'][0],settings['verify_token']):return self.reply(403)
            challenge=query.get('hub.challenge',[])
            if len(challenge)!=1 or not challenge[0].isdigit() or len(challenge[0])>200:return self.reply(400)
            return self.reply(200,challenge[0].encode('ascii'))
        except (PermissionError,FileNotFoundError):return self.reply(403)
        except (ValueError,TypeError):return self.reply(400)
        finally:
            if token is not None:llm._key_context.reset(token)

    def do_POST(self):
        event=re.fullmatch(r'/event/([\w-]{1,100})/([a-z0-9_-]{1,40})',urlsplit(self.path).path) if len(self.path)<=4096 else None
        if event:return self.event_post(event[1],event[2])
        token=None
        try:
            owner,_=self.owner();token=llm._key_context.set(owner)
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:return self.reply(400)
            size=int(self.headers['Content-Length'])
            if not 0<size<=message_inbox.MAX_BODY:return self.reply(413)
            self.connection.settimeout(2)
            body=self.rfile.read(size)
            if len(body)!=size:return self.reply(400)
            stored=message_inbox.ingest(owner,body,self.headers.get('X-Hub-Signature-256',''))
            notify=getattr(self.server,'notify',None)
            event_notify=getattr(self.server,'event_notify',None)
            self._gateway_event(owner,'mesaj',{'kind':'message'})
            if event_notify and stored['stored']:
                try:event_notify(owner, {'source':'whatsapp','kind':'incoming_batch','payload':stored})
                except Exception:
                    _record_failure('modules/webhook_server.py:event_notify')
            if notify and stored['stored']:
                try:notify(owner,stored)
                except Exception:
                    _record_failure('modules/webhook_server.py:notify')
            return self.reply(200,b'OK')
        except (PermissionError,FileNotFoundError):return self.reply(403)
        except (ValueError,TypeError,KeyError,AttributeError):return self.reply(400)
        except (OSError,TimeoutError,sqlite3.Error):return self.reply(503)
        finally:
            if token is not None:llm._key_context.reset(token)


def start(stop_event,owners,port=9898,notify=None,event_notify=None):
    global _SERVER
    # No listening port unless an existing profile explicitly enables a webhook.
    enabled=False
    for owner in (owners() if callable(owners) else owners):
        token=llm._key_context.set(owner)
        try:
            message_inbox.config(owner);enabled=True
        except (PermissionError,FileNotFoundError,ValueError):pass
        try:
            event_webhooks.config(owner);enabled=True
        except (PermissionError,FileNotFoundError,ValueError):pass
        finally:llm._key_context.reset(token)
    if not enabled:return
    with _LOCK:
        if _SERVER is not None:return
        try:server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        except OSError:return {'state':'unavailable','port':port}
        server.daemon_threads=True;_SERVER=server
        server.allowed_owners=owners
        server.notify=notify
        server.event_notify=event_notify
    threading.Thread(target=server.serve_forever,daemon=True,name='event-webhook').start()
    def close():
        global _SERVER
        stop_event.wait();server.shutdown();server.server_close()
        with _LOCK:_SERVER=None
    threading.Thread(target=close,daemon=True,name='webhook-close').start()
    return {'state':'listening','port':server.server_port}
