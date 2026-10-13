"""Idempotent, per-profile field-note ingestion shared by PC and phone."""
import re
from datetime import datetime
from modules.personalization import _LOCK

def list_notes(profile):
    with _LOCK:
        return list(profile.data.get('items', []))

def sync(profile, notes):
    if not isinstance(notes,list) or len(notes)>100:
        raise ValueError('En fazla 100 not gönderilebilir.')
    validated=[]
    for note in notes:
        if not isinstance(note,dict):raise ValueError('Geçersiz not')
        uid=str(note.get('uid',''));text=str(note.get('text','')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',uid) or not text or len(text)>20000:
            raise ValueError('Not kimliği veya metni geçersiz.')
        validated.append((uid,text))
    ack=[]
    with _LOCK:
        receipts=profile.data.setdefault('field_note_receipts',{})
        for uid,text in validated:
            if uid not in receipts:
                # One profile save commits the note and receipt together.
                item={'id':profile._new_id(),'text':text,'ts':datetime.now().strftime('%Y-%m-%d %H:%M'), 'source':'saha','uid':uid}
                profile.data.setdefault('items',[]).append(item)
                receipts[uid]=item['id']
            ack.append(uid)
        profile.save()
    return {'ack':ack,'notes':list_notes(profile),'user':profile.slug}
