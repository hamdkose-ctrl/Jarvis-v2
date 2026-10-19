"""Opt-in consuming poller: persist events before acknowledging a bot update."""
import hashlib
import time
from modules import service_store as store, message_inbox


def cursor(owner,token):
    key=hashlib.sha256(token.encode()).hexdigest()
    with store.database(owner) as db:
        db.execute('CREATE TABLE IF NOT EXISTS bot_cursors(bot_key TEXT PRIMARY KEY,last_update INTEGER)')
        row=db.execute('SELECT last_update FROM bot_cursors WHERE bot_key=?',(key,)).fetchone()
    return key,row[0] if row else None


def save(owner,key,updates,chat):
    latest=None
    with store.database(owner) as db:
        message_inbox._schema(db)
        for update in updates:
            uid=update.get('update_id')
            if type(uid) is not int or uid<0:raise ValueError('Bot güncelleme kimliği geçersiz.')
            latest=uid if latest is None else max(latest,uid)
            msg=update.get('message',{})
            if str(msg.get('chat',{}).get('id'))!=chat:continue
            text=msg.get('text')
            if not isinstance(text,str):continue
            db.execute('INSERT OR IGNORE INTO incoming VALUES(?,?,?,?,?,?,?,?)',
                       ('telegram',key+':'+str(uid),'message',chat,text[:4096],str(msg.get('date','')),time.time(),'{}'))
        if latest is not None:
            db.execute('INSERT INTO bot_cursors VALUES(?,?) ON CONFLICT(bot_key) DO UPDATE SET last_update=MAX(last_update,excluded.last_update)',(key,latest))
