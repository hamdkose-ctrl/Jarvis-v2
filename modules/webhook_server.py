"""Opt-in loopback-only WhatsApp webhook receiver. Public HTTPS is external setup."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import re
import threading
import sqlite3
from urllib.parse import urlsplit,parse_qs
from modules import llm, message_inbox, service_store
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
        allowed=getattr(self.server,'allowed_owners',None)
        if allowed is not None and match[1] not in (allowed() if callable(allowed) else allowed):raise PermissionError('Webhook kullanıcısı kayıtlı değil.')
        return match[1],parse_qs(parsed.query)

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
    threading.Thread(target=server.serve_forever,daemon=True,name='whatsapp-webhook').start()
    def close():
        global _SERVER
        stop_event.wait();server.shutdown();server.server_close()
        with _LOCK:_SERVER=None
    threading.Thread(target=close,daemon=True,name='webhook-close').start()
    return {'state':'listening','port':server.server_port}
