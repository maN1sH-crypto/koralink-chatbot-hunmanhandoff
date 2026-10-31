import os,re,uuid,io
from statistics import median
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
from bson import ObjectId
from flask import Flask,request,jsonify,render_template,send_file,Response
from flask_cors import CORS
from flask_socketio import SocketIO,emit,join_room
from pymongo import MongoClient,ReturnDocument
from gridfs import GridFSBucket
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

# Load .env for both `python app.py` and `flask run` before reading config.
load_dotenv()

import scap as scp
import groq_client

MONGODB_URI=os.getenv('MONGODB_URI') or os.getenv('MONGO_URI')
if not MONGODB_URI: raise RuntimeError('Set MONGO_URI or MONGODB_URI in your .env file')
DB=os.getenv('MONGODB_DB') or os.getenv('DATABASE_NAME','koralink'); SECRET=os.getenv('SECRET_KEY','CHANGE_ME')
app=Flask(__name__); app.config['SECRET_KEY']=SECRET
MAX_ATTACHMENT_SIZE=5*1024*1024
app.config['MAX_CONTENT_LENGTH']=MAX_ATTACHMENT_SIZE+256*1024
orig=[x.strip() for x in os.getenv('FRONTEND_ORIGIN','*').split(',') if x.strip()] or ['*']
CORS(app,resources={r'/api/.*':{'origins':orig},r'/chat':{'origins':orig}},supports_credentials=True)
socketio=SocketIO(app,cors_allowed_origins=orig,async_mode='threading')
client=MongoClient(MONGODB_URI,serverSelectionTimeoutMS=10000,connectTimeoutMS=10000,socketTimeoutMS=30000); client.admin.command('ping'); db=client[DB]
convs=db.conversations; msgs=db.messages; agents=db.agents
knowledge=db[os.getenv('COLLECTION_NAME','knowledge')]
attachments=GridFSBucket(db,bucket_name='chat_attachments')
convs.create_index([('status',1),('created_at',1)]); convs.create_index([('agent_id',1),('status',1)]); msgs.create_index([('conversation_id',1),('created_at',1)]); agents.create_index('email',unique=True)
PATTERNS=[r'\btalk\s+(?:(?:to|with)\s+)?(?:(?:a|an)\s+)?(?:human|agent)\b',r'\bspeak\s+(?:(?:to|with)\s+)?(?:(?:a|an)\s+)?(?:human|agent)\b',r'\bconnect me (?:to|with)\s+(?:(?:a|an)\s+)?(?:human|agent)\b',r'\bi want (?:to )?(?:talk|speak)\s+(?:(?:to|with)\s+)?(?:(?:a|an)\s+)?(?:human|agent)\b',r'\bi need\s+(?:(?:a|an)\s+)?(?:human|agent)\b',r'\bhuman support\b',r'\blive support\b',r'\breal person\b',r'\blive person\b',r'\brepresentative\b',r'\bcustomer (support|service)\b',r'\binsaan se baat\b',r'\bagent se baat\b']
def now(): return datetime.now(timezone.utc)
def clean(x,maxlen=2000): return x.strip()[:maxlen] if isinstance(x,str) else ''
def wants_human(x): return any(re.search(p,x.lower()) for p in PATTERNS)
def affirmative(x): return bool(re.match(r'^(yes|yeah|yep|sure|ok|okay|yego)\b',x.strip().lower()))
def negative(x): return bool(re.match(r'^(no|nope|nah|oya)\b',x.strip().lower()))
def cj(d): return {'id':str(d['_id']),'customer_id':d.get('customer_id'),'status':d.get('status'),'agent_id':d.get('agent_id'),'created_at':d.get('created_at').isoformat() if d.get('created_at') else None,'updated_at':d.get('updated_at').isoformat() if d.get('updated_at') else None,'closed_at':d.get('closed_at').isoformat() if d.get('closed_at') else None,'handoff_requested_at':d.get('handoff_requested_at').isoformat() if d.get('handoff_requested_at') else None,'estimated_wait_seconds':d.get('estimated_wait_seconds')}
def mj(d): return {'id':str(d['_id']),'conversation_id':d['conversation_id'],'sender_type':d['sender_type'],'sender_id':d.get('sender_id'),'message':d['message'],'payload':d.get('payload',{}),'created_at':d.get('created_at').isoformat() if d.get('created_at') else None}
def save(cid,typ,text,sid=None,payload=None):
 d={'conversation_id':str(cid),'sender_type':typ,'sender_id':sid,'message':text,'payload':payload or {},'created_at':now()}; r=msgs.insert_one(d); d['_id']=r.inserted_id; convs.update_one({'_id':ObjectId(cid)},{'$set':{'updated_at':now()}}); return d
def estimate_wait_minutes(conversation):
 # Estimate from recent agent handling times; use a clearly approximate 10-minute
 # fallback until this deployment has enough conversations with claimed_at data.
 durations=[]
 for past in convs.find({'status':'closed','claimed_at':{'$exists':True},'closed_at':{'$exists':True}},{'claimed_at':1,'closed_at':1}).sort('closed_at',-1).limit(50):
  duration=(past['closed_at']-past['claimed_at']).total_seconds()/60
  if 1 <= duration <= 120: durations.append(duration)
 average_minutes=median(durations) if durations else 10
 online_agents=list(agents.find({'active':True,'online':True},{'_id':1}))
 if not online_agents: return None
 agent_ids=[str(agent['_id']) for agent in online_agents]
 position=convs.count_documents({'status':'waiting_human','created_at':{'$lt':conversation['created_at']}})+1
 active_count=convs.count_documents({'status':'human_active','agent_id':{'$in':agent_ids}})
 busy_workload=max(1,active_count+position-1)
 return max(1,round(busy_workload*average_minutes/len(online_agents)))
def waiting_reply(conversation,language='English'):
 minutes=estimate_wait_minutes(conversation)
 if minutes is None:
  message='Your request is in the support queue. No agents are online right now, so an estimated wait time is not available yet.'
 else:
  message=f'Your request is in the support queue. The estimated wait is about {minutes} minute'+('s' if minutes!=1 else '')+'. This is an approximate estimate based on recent support response times and the current queue.'
 if language.lower()!='english': message=groq_client.translate_text(message,language)
 return message
def expire_handoff(cid):
 cutoff=now()-timedelta(minutes=2)
 d=convs.find_one_and_update({'_id':ObjectId(cid),'status':'waiting_human','handoff_requested_at':{'$lte':cutoff}},{'$set':{'status':'bot_active','updated_at':now()},'$unset':{'handoff_requested_at':'','estimated_wait_seconds':''}},return_document=ReturnDocument.AFTER)
 if not d: return False
 message='Sorry, no supervisor or support agent joined within two minutes. You can continue with AI support, or say “talk to a human” to try connecting again.'
 language=d.get('reply_language','English')
 if language.lower()!='english':
  try: message=groq_client.translate_text(message,language)
  except Exception: app.logger.exception('Could not translate the human-handoff timeout notice')
 notice=save(cid,'system',message)
 emit_conv(cid,'new_message',mj(notice)); socketio.emit('queue_updated',{},room='agents')
 return True
def expire_due_handoffs():
 cutoff=now()-timedelta(minutes=2)
 for d in convs.find({'status':'waiting_human','handoff_requested_at':{'$lte':cutoff}},{'_id':1}).limit(100):
  expire_handoff(str(d['_id']))
def purge_conversation_attachments(cid):
 for f in db['chat_attachments.files'].find({'metadata.conversation_id':str(cid)},{'_id':1}):
  try: attachments.delete(f['_id'])
  except Exception: app.logger.exception('Could not delete chat attachment %s',f['_id'])
 msgs.update_many({'conversation_id':str(cid),'payload.attachment':{'$exists':True}},{'$set':{'message':'Image attachment removed when the conversation closed.'},'$unset':{'payload.attachment':''}})
def emit_conv(cid,event,data): socketio.emit(event,data,room='conversation:'+str(cid))
def agent_req():
 t=request.headers.get('X-Agent-Token'); return agents.find_one({'session_token':t,'active':True}) if t else None
def req_agent():
 a=agent_req(); return (a,None) if a else (None,(jsonify({'error':'Agent authentication required'}),401))
def req_admin():
 a,e=req_agent()
 if e:return None,e
 if a.get('role') not in ('admin','superadmin'):return None,(jsonify({'error':'Knowledge base admin access required'}),403)
 return a,None
def getconv(cid,cust=None):
 try: q={'_id':ObjectId(cid)}; q.update({'customer_id':cust} if cust else {}); return convs.find_one(q)
 except: return None

@app.get('/health')
def health():
 try: client.admin.command('ping'); return jsonify(ok=True,mongodb='connected')
 except: return jsonify(ok=False),503

@app.post('/api/customer/session')
def customer_session():
 cid=str(uuid.uuid4()); d={'customer_id':cid,'status':'bot_active','agent_id':None,'created_at':now(),'updated_at':now(),'closed_at':None}; r=convs.insert_one(d); d['_id']=r.inserted_id; return jsonify(customer_id=cid,conversation=cj(d))

@app.get('/api/customer/conversation/<cid>')
def customer_history(cid):
 cust=clean(request.args.get('customer_id','')); d=getconv(cid,cust)
 if not d:return jsonify(error='Conversation not found'),404
 expire_handoff(cid); d=getconv(cid,cust)
 return jsonify(conversation=cj(d),messages=[mj(x) for x in msgs.find({'conversation_id':cid}).sort('created_at',1).limit(500)])

@app.post('/api/customer/message')
def customer_message():
 data=request.get_json(silent=True) or {}; cust=clean(data.get('customer_id')); cid=clean(data.get('conversation_id')); text=clean(data.get('message'))
 if not cust:cust=str(uuid.uuid4())
 if not text:return jsonify(error='message is required'),400
 d=getconv(cid,cust) if cid else None
 # Mobile browsers may keep an old conversation ID after an agent closes it.
 # Start a fresh bot conversation for the same customer instead of returning
 # 409, so the next message resumes normally even if the page missed the event.
 if not d or d.get('status')=='closed':
  d={'customer_id':cust,'status':'bot_active','agent_id':None,'created_at':now(),'updated_at':now(),'closed_at':None}; r=convs.insert_one(d); d['_id']=r.inserted_id
 cid=str(d['_id'])
 cm=save(cid,'customer',text,cust); emit_conv(cid,'new_message',mj(cm))
 if d['status']=='human_active': return jsonify(customer_id=cust,conversation=cj(d),mode='human',response=None,images=[],step_images={})
 if d['status']=='waiting_human':
  expire_handoff(cid); d=getconv(cid,cust)
 if d['status']=='waiting_human':
  _,reply_language=groq_client.detect_language_and_translate_to_english(text)
  queue_text=waiting_reply(d,reply_language)
  s=save(cid,'bot',queue_text); emit_conv(cid,'new_message',mj(s)); return jsonify(customer_id=cust,conversation=cj(d),mode='waiting_human',response=s['message'],images=[],step_images={})
 try:
  search_text,reply_language=groq_client.detect_language_and_translate_to_english(text)
  followup_state=d.get('followup_state')
  if followup_state=='awaiting_satisfaction' and affirmative(search_text):
   convs.update_one({'_id':ObjectId(cid)},{'$unset':{'followup_state':''}})
   answer='Great, I’m glad that helped. What else can I help you with?'
   if reply_language.lower()!='english': answer=groq_client.translate_text(answer,reply_language)
   s=save(cid,'bot',answer); emit_conv(cid,'new_message',mj(s))
   return jsonify(customer_id=cust,conversation=cj(d),mode='bot',response=s['message'],images=[],step_images={})
  if followup_state=='awaiting_satisfaction' and negative(search_text):
   convs.update_one({'_id':ObjectId(cid)},{'$set':{'followup_state':'awaiting_supervisor'}})
   answer='Would you like to speak with a supervisor? Reply Yes to connect, or No to continue with AI support.'
   if reply_language.lower()!='english': answer=groq_client.translate_text(answer,reply_language)
   s=save(cid,'bot',answer); emit_conv(cid,'new_message',mj(s))
   return jsonify(customer_id=cust,conversation=cj(d),mode='bot',response=s['message'],images=[],step_images={})
  wants_supervisor=followup_state=='awaiting_supervisor' and affirmative(search_text)
  if followup_state=='awaiting_supervisor' and negative(search_text):
   convs.update_one({'_id':ObjectId(cid)},{'$unset':{'followup_state':''}})
   answer='Okay, I’ll keep helping with AI support. What would you like to know?'
   if reply_language.lower()!='english': answer=groq_client.translate_text(answer,reply_language)
   s=save(cid,'bot',answer); emit_conv(cid,'new_message',mj(s))
   return jsonify(customer_id=cust,conversation=cj(d),mode='bot',response=s['message'],images=[],step_images={})
  if followup_state:
   convs.update_one({'_id':ObjectId(cid)},{'$unset':{'followup_state':''}})
  if wants_human(search_text) or wants_supervisor:
   handoff_time=now(); estimated_minutes=estimate_wait_minutes(d)
   d=convs.find_one_and_update({'_id':ObjectId(cid),'status':{'$in':['bot_active','waiting_human']}},{'$set':{'status':'waiting_human','updated_at':handoff_time,'handoff_requested_at':handoff_time,'estimated_wait_seconds':estimated_minutes*60 if estimated_minutes is not None else None,'reply_language':reply_language},'$unset':{'followup_state':''}},return_document=ReturnDocument.AFTER)
   wait_text='Sure. I’m connecting you with a KoraLink support agent. '+waiting_reply(d,reply_language)
   s=save(cid,'bot',wait_text)
   emit_conv(cid,'new_message',mj(s)); socketio.emit('queue_updated',{},room='agents')
   return jsonify(customer_id=cust,conversation=cj(d),mode='waiting_human',response=s['message'],images=[],step_images={})
  result=scp.answer_finder(search_text); answer=result['answer']; images=result['images']; steps=result['step_images']
  answer+='\n\nDid this answer solve your issue? Reply Yes if it did, or No if you still need help.'
  if reply_language.lower()!='english':answer,images,steps=groq_client.translate_answer_and_images(answer,images,reply_language,steps)
  answer=answer.replace('â€“','-').replace('â€”','-').replace('â€','')
 except Exception:
  app.logger.exception('Chatbot or language translation error'); return jsonify(error='Chatbot processing failed. Please try again or contact support.'),502
 convs.update_one({'_id':ObjectId(cid)},{'$set':{'followup_state':'awaiting_satisfaction'}})
 bm=save(cid,'bot',answer,payload={'images':images,'step_images':steps}); emit_conv(cid,'new_message',mj(bm))
 return jsonify(customer_id=cust,conversation=cj(d),mode='bot',response=answer,images=images,step_images=steps)

@app.post('/api/agent/login')
def login():
 x=request.get_json(silent=True) or {}; email=clean(x.get('email')).lower(); pw=x.get('password',''); a=agents.find_one({'email':email,'active':True})
 if not a or not check_password_hash(a.get('password_hash',''),pw):return jsonify(error='Invalid email or password'),401
 t=str(uuid.uuid4()); agents.update_one({'_id':a['_id']},{'$set':{'session_token':t,'online':True,'last_seen':now()}}); return jsonify(token=t,agent={'id':str(a['_id']),'name':a.get('name',''),'email':a.get('email',''),'role':a.get('role','agent')})
@app.post('/api/agent/logout')
def logout():
 a,e=req_agent()
 if e:return e
 agents.update_one({'_id':a['_id']},{'$set':{'online':False,'last_seen':now()},'$unset':{'session_token':''}}); return jsonify(ok=True)
@app.get('/api/agent/me')
def agent_me():
 a,e=req_agent()
 if e:return e
 return jsonify(agent={'id':str(a['_id']),'name':a.get('name',''),'email':a.get('email',''),'role':a.get('role','agent')})
@app.get('/api/agent/queue')
def queue():
 a,e=req_agent()
 if e:return e
 expire_due_handoffs()
 out=[]
 for d in convs.find({'status':'waiting_human'}).sort('created_at',1).limit(100):
  last=msgs.find_one({'conversation_id':str(d['_id'])},sort=[('created_at',-1)]); out.append({**cj(d),'last_message':mj(last) if last else None})
 return jsonify(conversations=out)
@app.get('/api/agent/active')
def active():
 a,e=req_agent()
 if e:return e
 return jsonify(conversations=[cj(d) for d in convs.find({'status':'human_active','agent_id':str(a['_id'])}).sort('updated_at',-1)])
@app.get('/api/agent/conversation/<cid>')
def agent_history(cid):
 a,e=req_agent()
 if e:return e
 d=getconv(cid)
 if not d:return jsonify(error='Conversation not found'),404
 expire_handoff(cid); d=getconv(cid)
 return jsonify(conversation=cj(d),messages=[mj(x) for x in msgs.find({'conversation_id':cid}).sort('created_at',1).limit(500)])
@app.post('/api/agent/conversation/<cid>/claim')
def claim(cid):
 a,e=req_agent()
 if e:return e
 d=convs.find_one_and_update({'_id':ObjectId(cid),'status':'waiting_human','agent_id':None},{'$set':{'status':'human_active','agent_id':str(a['_id']),'claimed_at':now(),'updated_at':now()},'$unset':{'handoff_requested_at':'','estimated_wait_seconds':''}},return_document=ReturnDocument.AFTER)
 if not d:return jsonify(error='Conversation was already claimed or is unavailable'),409
 s=save(cid,'system',f"{a.get('name','A support agent')} has joined the conversation.",str(a['_id'])); emit_conv(cid,'conversation_claimed',{'conversation':cj(d)}); emit_conv(cid,'new_message',mj(s)); socketio.emit('queue_updated',{},room='agents'); return jsonify(conversation=cj(d))
@app.post('/api/agent/conversation/<cid>/message')
def agent_message(cid):
 a,e=req_agent()
 if e:return e
 text=clean((request.get_json(silent=True) or {}).get('message')); d=getconv(cid)
 if not text:return jsonify(error='message is required'),400
 if not d or d.get('status')!='human_active':return jsonify(error='Conversation is not active'),409
 if d.get('agent_id')!=str(a['_id']):return jsonify(error='You do not own this conversation'),403
 m=save(cid,'agent',text,str(a['_id'])); emit_conv(cid,'new_message',mj(m)); return jsonify(message=mj(m))

@app.post('/api/agent/conversation/<cid>/attachment')
def agent_attachment(cid):
 a,e=req_agent()
 if e:return e
 d=getconv(cid)
 if not d or d.get('status')!='human_active':return jsonify(error='Conversation is not active'),409
 if d.get('agent_id')!=str(a['_id']):return jsonify(error='You do not own this conversation'),403
 upload=request.files.get('file')
 if not upload:return jsonify(error='Choose an image to upload'),400
 content=upload.stream.read(MAX_ATTACHMENT_SIZE+1)
 if not content:return jsonify(error='The selected image is empty'),400
 if len(content)>MAX_ATTACHMENT_SIZE:return jsonify(error='Images must be 5 MB or smaller'),413
 image_types=[(b'\x89PNG\r\n\x1a\n','image/png','.png'),(b'\xff\xd8\xff','image/jpeg','.jpg'),(b'GIF87a','image/gif','.gif'),(b'GIF89a','image/gif','.gif')]
 detected=next(((mime,ext) for signature,mime,ext in image_types if content.startswith(signature)),None)
 if not detected and len(content)>=12 and content.startswith(b'RIFF') and content[8:12]==b'WEBP':detected=('image/webp','.webp')
 if not detected:return jsonify(error='Supported image formats: PNG, JPG, GIF, and WEBP'),415
 content_type,extension=detected
 from werkzeug.utils import secure_filename
 original=secure_filename(upload.filename or '')
 filename=original if original and os.path.splitext(original)[1].lower()==extension else 'support-image'+extension
 metadata={'conversation_id':cid,'customer_id':d.get('customer_id'),'agent_id':str(a['_id']),'content_type':content_type}
 file_id=attachments.upload_from_stream(filename,io.BytesIO(content),metadata=metadata)
 latest=getconv(cid)
 if not latest or latest.get('status')!='human_active' or latest.get('agent_id')!=str(a['_id']):
  attachments.delete(file_id)
  return jsonify(error='The conversation was closed before the image finished uploading'),409
 m=save(cid,'agent',f'Shared an image: {filename}',str(a['_id']),payload={'attachment':{'file_id':str(file_id),'filename':filename,'content_type':content_type}})
 emit_conv(cid,'new_message',mj(m))
 return jsonify(message=mj(m)),201

@app.post('/api/customer/conversation/<cid>/attachment')
def customer_attachment(cid):
 customer=clean(request.form.get('customer_id'))
 d=getconv(cid,customer)
 if not d:return jsonify(error='Conversation not found'),404
 if d.get('status') not in ('waiting_human','human_active'):
  return jsonify(error='You can share an image while waiting for or chatting with support'),409
 upload=request.files.get('file')
 if not upload:return jsonify(error='Choose an image to upload'),400
 content=upload.stream.read(MAX_ATTACHMENT_SIZE+1)
 if not content:return jsonify(error='The selected image is empty'),400
 if len(content)>MAX_ATTACHMENT_SIZE:return jsonify(error='Images must be 5 MB or smaller'),413
 image_types=[(b'\x89PNG\r\n\x1a\n','image/png','.png'),(b'\xff\xd8\xff','image/jpeg','.jpg'),(b'GIF87a','image/gif','.gif'),(b'GIF89a','image/gif','.gif')]
 detected=next(((mime,ext) for signature,mime,ext in image_types if content.startswith(signature)),None)
 if not detected and len(content)>=12 and content.startswith(b'RIFF') and content[8:12]==b'WEBP':detected=('image/webp','.webp')
 if not detected:return jsonify(error='Supported image formats: PNG, JPG, GIF, and WEBP'),415
 content_type,extension=detected
 from werkzeug.utils import secure_filename
 original=secure_filename(upload.filename or '')
 filename=original if original and os.path.splitext(original)[1].lower()==extension else 'customer-image'+extension
 metadata={'conversation_id':cid,'customer_id':customer,'sender_type':'customer','content_type':content_type}
 file_id=attachments.upload_from_stream(filename,io.BytesIO(content),metadata=metadata)
 latest=getconv(cid,customer)
 if not latest or latest.get('status') not in ('waiting_human','human_active'):
  attachments.delete(file_id)
  return jsonify(error='The conversation was closed before the image finished uploading'),409
 m=save(cid,'customer',f'Customer shared an image: {filename}',customer,payload={'attachment':{'file_id':str(file_id),'filename':filename,'content_type':content_type}})
 emit_conv(cid,'new_message',mj(m)); socketio.emit('queue_updated',{},room='agents')
 return jsonify(message=mj(m)),201

@app.get('/api/customer/conversation/<cid>/attachment/<file_id>')
def conversation_attachment(cid,file_id):
 d=getconv(cid,clean(request.args.get('customer_id','')) or None)
 if not d:return jsonify(error='Conversation not found'),404
 try:file=attachments.open_download_stream(ObjectId(file_id))
 except Exception:return jsonify(error='Image not found'),404
 metadata=file.metadata or {}
 if metadata.get('conversation_id')!=cid:return jsonify(error='Image not found'),404
 token=request.headers.get('X-Agent-Token') or clean(request.args.get('agent_token',''))
 agent=agents.find_one({'session_token':token,'active':True}) if token else None
 has_customer_access=bool(request.args.get('customer_id')) and d.get('customer_id')==request.args.get('customer_id')
 if not has_customer_access and not agent:return jsonify(error='Authentication required'),401
 return Response(file.read(),mimetype=metadata.get('content_type','application/octet-stream'),headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
@app.post('/api/agent/conversation/<cid>/close')
def close(cid):
 a,e=req_agent()
 if e:return e
 d=convs.find_one_and_update({'_id':ObjectId(cid),'status':'human_active','agent_id':str(a['_id'])},{'$set':{'status':'closed','closed_at':now(),'updated_at':now()}},return_document=ReturnDocument.AFTER)
 if not d:return jsonify(error='Conversation not found or not owned by you'),404
 m=save(cid,'system','The support conversation has been closed. You can start a new chat if you need more help.'); purge_conversation_attachments(cid); emit_conv(cid,'conversation_closed',{'conversation':cj(d)}); emit_conv(cid,'new_message',mj(m)); socketio.emit('queue_updated',{},room='agents'); return jsonify(conversation=cj(d))

@socketio.on('connect')
def connected(): emit('connected',{'ok':True})
@socketio.on('join_customer')
def join_customer(data):
 cid=clean((data or {}).get('conversation_id')); cust=clean((data or {}).get('customer_id')); d=getconv(cid,cust)
 if not d: return emit('socket_error',{'error':'Conversation not found'})
 join_room('conversation:'+cid); emit('joined',{'conversation_id':cid})
@socketio.on('join_agent')
def join_agent(data):
 a=agents.find_one({'session_token':clean((data or {}).get('token')),'active':True})
 if not a:return emit('socket_error',{'error':'Agent authentication required'})
 join_room('agents'); emit('joined',{'room':'agents'})
@socketio.on('join_conversation_as_agent')
def join_agent_conv(data):
 a=agents.find_one({'session_token':clean((data or {}).get('token')),'active':True}); cid=clean((data or {}).get('conversation_id'))
 if not a:return emit('socket_error',{'error':'Agent authentication required'})
 d=getconv(cid)
 if not d or d.get('status')!='human_active' or d.get('agent_id')!=str(a['_id']):return emit('socket_error',{'error':'Conversation not owned by this agent'})
 join_room('conversation:'+cid); emit('joined',{'conversation_id':cid})
@app.get('/agent')
def agent_page(): return render_template('agent_dashboard.html')

@app.get('/knowledge')
def knowledge_page(): return render_template('knowledge_manager.html')

def knowledge_json(document):
 result={key:value for key,value in document.items() if key!='_id'}
 result['id']=str(document['_id'])
 # Present bilingual legacy records as one English-only editing view.
 result['question']=result.get('question_en') or result.get('question','')
 result['answer']=result.get('answer_en') or result.get('answer','')
 result['keywords']=result.get('keywords_en') or result.get('keywords',[])
 result.pop('question_en',None); result.pop('answer_en',None); result.pop('keywords_en',None)
 result.setdefault('keywords',[])
 result.setdefault('active',True)
 if not result.get('images') and result.get('image'):
  legacy=result['image']
  result['images']=legacy if isinstance(legacy,list) else [legacy]
 result['images']=[{**image,'alt':image.get('alt_en') or image.get('alt',''),'caption':image.get('caption_en') or image.get('caption','')} if isinstance(image,dict) else image for image in result.get('images',[])]
 for image in result['images']:
  if isinstance(image,dict):image.pop('alt_en',None); image.pop('caption_en',None)
 result.pop('image',None)
 return result

def clean_knowledge_images(value):
 if not isinstance(value,list):raise ValueError('Images must be a list of image URL records')
 images=[]
 for image in value:
  if isinstance(image,str):image={'src':image}
  if not isinstance(image,dict):raise ValueError('Each image must have a URL')
  src=clean(image.get('src') or image.get('url'),2000)
  if not src:continue
  parsed=urlsplit(src)
  if parsed.scheme not in ('http','https') or not parsed.netloc:raise ValueError('Image URLs must start with http:// or https://')
  images.append({'type':clean(image.get('type','screenshot'),80) or 'screenshot','src':src,'alt':clean(image.get('alt',''),300),'caption':clean(image.get('caption',''),500)})
 if len(images)>50:raise ValueError('An entry can have at most 50 images')
 return images

def duplicate_knowledge_question(question, exclude_id=None):
 key=' '.join(question.lower().split())
 query={'$or':[{'question_key':key},{'question':re.compile(r'^\s*'+re.escape(question.strip())+r'\s*$',re.IGNORECASE)}]}
 if exclude_id:query['_id']={'$ne':exclude_id}
 return knowledge.find_one(query)

@app.get('/api/admin/knowledge')
def knowledge_search():
 a,e=req_admin()
 if e:return e
 query=clean(request.args.get('q',''),300)
 try: page=max(1,int(request.args.get('page',1)))
 except (TypeError,ValueError):page=1
 try: limit=min(50,max(1,int(request.args.get('limit',20))))
 except (TypeError,ValueError):limit=20
 filters={}
 if query:
  pattern=re.compile(re.escape(query),re.IGNORECASE)
  filters={'$or':[{'question':pattern},{'answer':pattern},{'keywords':pattern},{'question_en':pattern},{'answer_en':pattern},{'keywords_en':pattern}]}
 total=knowledge.count_documents(filters)
 docs=knowledge.find(filters).sort('question',1).skip((page-1)*limit).limit(limit)
 return jsonify(items=[knowledge_json(d) for d in docs],total=total,page=page,pages=max(1,(total+limit-1)//limit))

@app.post('/api/admin/knowledge')
def knowledge_create():
 a,e=req_admin()
 if e:return e
 data=request.get_json(silent=True) or {}; question=clean(data.get('question'),500); answer=clean(data.get('answer'),10000)
 if not question or not answer:return jsonify(error='Question and answer are required'),400
 key=' '.join(question.lower().split())
 if duplicate_knowledge_question(question):return jsonify(error='A question with this wording already exists'),409
 raw_keywords=data.get('keywords',[])
 if isinstance(raw_keywords,str):raw_keywords=raw_keywords.splitlines()
 if not isinstance(raw_keywords,list) or not all(isinstance(item,str) for item in raw_keywords):return jsonify(error='Keywords must be a list of text values'),400
 try:images_value=clean_knowledge_images(data.get('images',[]))
 except ValueError as error:return jsonify(error=str(error)),400
 document={'question':question,'answer':answer,'keywords':[x.strip() for x in raw_keywords if x.strip()],'images':images_value,'question_key':key,'active':bool(data.get('active',True)),'created_at':now(),'updated_at':now()}
 for field in ('category','language'):
  if clean(data.get(field)):document[field]=clean(data[field],100)
 result=knowledge.insert_one(document); document['_id']=result.inserted_id
 try:scp.bot.reload_knowledge_base(); refreshed=True
 except Exception:app.logger.exception('Knowledge entry saved but chatbot index refresh failed'); refreshed=False
 return jsonify(item=knowledge_json(document),chatbot_refreshed=refreshed),201

@app.put('/api/admin/knowledge/<entry_id>')
def knowledge_update(entry_id):
 a,e=req_admin()
 if e:return e
 if not ObjectId.is_valid(entry_id):return jsonify(error='Invalid knowledge entry ID'),400
 current=knowledge.find_one({'_id':ObjectId(entry_id)})
 if not current:return jsonify(error='Knowledge entry not found'),404
 data=request.get_json(silent=True) or {}; question=clean(data.get('question'),500); answer=clean(data.get('answer'),10000)
 if not question or not answer:return jsonify(error='Question and answer are required'),400
 raw_keywords=data.get('keywords',[])
 if isinstance(raw_keywords,str):raw_keywords=raw_keywords.splitlines()
 if not isinstance(raw_keywords,list) or not all(isinstance(item,str) for item in raw_keywords):return jsonify(error='Keywords must be a list of text values'),400
 legacy_images=current.get('image')
 existing_images=current.get('images') or (legacy_images if isinstance(legacy_images,list) else ([legacy_images] if legacy_images else []))
 try:images_value=clean_knowledge_images(data.get('images',existing_images))
 except ValueError as error:return jsonify(error=str(error)),400
 key=' '.join(question.lower().split())
 duplicate=duplicate_knowledge_question(question,current['_id'])
 if duplicate:return jsonify(error='Another entry already uses this question'),409
 fields={'question':question,'answer':answer,'keywords':[x.strip() for x in raw_keywords if x.strip()],'images':images_value,'question_key':key,'active':bool(data.get('active',True)),'updated_at':now()}
 for field in ('category','language'):
  value=clean(data.get(field),100)
  if value:fields[field]=value
  else:fields.pop(field,None)
 unset_fields={k:'' for k in ('category','language') if not fields.get(k)}
 unset_fields['image']=''
 unset_fields.update({'question_en':'','answer_en':'','keywords_en':''})
 knowledge.update_one({'_id':current['_id']},{'$set':fields,'$unset':unset_fields})
 updated=knowledge.find_one({'_id':current['_id']})
 try:scp.bot.reload_knowledge_base(); refreshed=True
 except Exception:app.logger.exception('Knowledge entry saved but chatbot index refresh failed'); refreshed=False
 return jsonify(item=knowledge_json(updated),chatbot_refreshed=refreshed)

@app.delete('/api/admin/knowledge/<entry_id>')
def knowledge_delete(entry_id):
 a,e=req_admin()
 if e:return e
 if not ObjectId.is_valid(entry_id):return jsonify(error='Invalid knowledge entry ID'),400
 result=knowledge.delete_one({'_id':ObjectId(entry_id)})
 if not result.deleted_count:return jsonify(error='Knowledge entry not found'),404
 try:scp.bot.reload_knowledge_base(); refreshed=True
 except Exception:app.logger.exception('Knowledge entry deleted but chatbot index refresh failed'); refreshed=False
 return jsonify(ok=True,chatbot_refreshed=refreshed)

@app.get('/api/admin/knowledge/export')
def knowledge_export():
 a,e=req_admin()
 if e:return e
 records=[]
 for item in knowledge.find({}).sort('question',1):
  item=knowledge_json(item)
  for field in ('id','question_key','created_at','updated_at','language'):
   item.pop(field,None)
  records.append(item)
 return Response(__import__('json').dumps(records,ensure_ascii=False,indent=2,default=str),mimetype='application/json',headers={'Content-Disposition':'attachment; filename=koralink_knowledge_backup.json'})

@app.route("/")
def home():
    return send_file("index.html")
@app.route("/chat", methods=["POST"])
def legacy_chat():
    try:
        data = request.get_json() or {}

        message = data.get("message", "").strip()
        if not message:
            return jsonify({
                "error": "Message is required"
            }), 400

        search_text, reply_language = groq_client.detect_language_and_translate_to_english(message)
        result = scp.answer_finder(search_text)

        answer = result.get("answer", "")
        images = result.get("images", [])
        step_images = result.get("step_images", [])
        if reply_language.lower() != "english":
            answer, images, step_images = groq_client.translate_answer_and_images(answer, images, reply_language, step_images)

        # Fix encoding issues
        answer = (
            answer
            .replace("â€“", "-")
            .replace("â€”", "-")
            .replace("â€", "")
        )

        return jsonify({
            "response": answer,
            "images": images,
            "step_images": step_images
        })

    except Exception as e:
        print("CHAT ERROR:", e)

        return jsonify({
            "error": "Something went wrong while processing the message."
        }), 500
    
if __name__=='__main__': socketio.run(app,host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=False,allow_unsafe_werkzeug=True)
