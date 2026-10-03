import os,re,uuid
from datetime import datetime,timezone
from bson import ObjectId
from flask import Flask,request,jsonify,render_template, send_file
from flask_cors import CORS
from flask_socketio import SocketIO,emit,join_room
from pymongo import MongoClient,ReturnDocument
from werkzeug.security import check_password_hash
import scap as scp
from deep_translator import GoogleTranslator

MONGODB_URI=os.getenv('MONGO_URI')
if not MONGODB_URI: raise RuntimeError('MONGODB_URI is required')
DB=os.getenv('MONGODB_DB','koralink'); SECRET=os.getenv('SECRET_KEY','CHANGE_ME')
app=Flask(__name__); app.config['SECRET_KEY']=SECRET
orig=[x.strip() for x in os.getenv('FRONTEND_ORIGIN','*').split(',') if x.strip()] or ['*']
CORS(app,resources={r'/api/*':{'origins':orig}},supports_credentials=True)
socketio=SocketIO(app,cors_allowed_origins=orig,async_mode='threading')
client=MongoClient(MONGODB_URI,serverSelectionTimeoutMS=10000,connectTimeoutMS=10000,socketTimeoutMS=30000); client.admin.command('ping'); db=client[DB]
convs=db.conversations; msgs=db.messages; agents=db.agents
convs.create_index([('status',1),('created_at',1)]); convs.create_index([('agent_id',1),('status',1)]); msgs.create_index([('conversation_id',1),('created_at',1)]); agents.create_index('email',unique=True)
PATTERNS=[r'\btalk to (a|an)?\s*human\b',r'\btalk to (a|an)?\s*agent\b',r'\bspeak to (a|an)?\s*(human|agent)\b',r'\bconnect me (to|with) (a|an)?\s*(human|agent)\b',r'\bi want (to )?(talk|speak) (to|with) (a|an)?\s*(human|agent)\b',r'\bi need (a|an)?\s*(human|agent)\b',r'\bhuman support\b',r'\blive support\b']
def now(): return datetime.now(timezone.utc)
def clean(x,maxlen=2000): return x.strip()[:maxlen] if isinstance(x,str) else ''
def wants_human(x): return any(re.search(p,x.lower()) for p in PATTERNS)
def cj(d): return {'id':str(d['_id']),'customer_id':d.get('customer_id'),'status':d.get('status'),'agent_id':d.get('agent_id'),'created_at':d.get('created_at').isoformat() if d.get('created_at') else None,'updated_at':d.get('updated_at').isoformat() if d.get('updated_at') else None,'closed_at':d.get('closed_at').isoformat() if d.get('closed_at') else None}
def mj(d): return {'id':str(d['_id']),'conversation_id':d['conversation_id'],'sender_type':d['sender_type'],'sender_id':d.get('sender_id'),'message':d['message'],'payload':d.get('payload',{}),'created_at':d.get('created_at').isoformat() if d.get('created_at') else None}
def save(cid,typ,text,sid=None,payload=None):
 d={'conversation_id':str(cid),'sender_type':typ,'sender_id':sid,'message':text,'payload':payload or {},'created_at':now()}; r=msgs.insert_one(d); d['_id']=r.inserted_id; convs.update_one({'_id':ObjectId(cid)},{'$set':{'updated_at':now()}}); return d
def emit_conv(cid,event,data): socketio.emit(event,data,room='conversation:'+str(cid))
def agent_req():
 t=request.headers.get('X-Agent-Token'); return agents.find_one({'session_token':t,'active':True}) if t else None
def req_agent():
 a=agent_req(); return (a,None) if a else (None,(jsonify({'error':'Agent authentication required'}),401))
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
 return jsonify(conversation=cj(d),messages=[mj(x) for x in msgs.find({'conversation_id':cid}).sort('created_at',1).limit(500)])

@app.post('/api/customer/message')
def customer_message():
 data=request.get_json(silent=True) or {}; cust=clean(data.get('customer_id')); cid=clean(data.get('conversation_id')); text=clean(data.get('message')); lang=clean(data.get('language','en')) or 'en'
 if not cust:cust=str(uuid.uuid4())
 if not text:return jsonify(error='message is required'),400
 d=getconv(cid,cust) if cid else None
 if not d:
  d={'customer_id':cust,'status':'bot_active','agent_id':None,'created_at':now(),'updated_at':now(),'closed_at':None}; r=convs.insert_one(d); d['_id']=r.inserted_id
 cid=str(d['_id'])
 if d['status']=='closed':return jsonify(error='Conversation is closed'),409
 cm=save(cid,'customer',text,cust); emit_conv(cid,'new_message',mj(cm))
 if d['status']=='human_active': return jsonify(customer_id=cust,conversation=cj(d),mode='human',response=None,images=[],step_images={})
 if wants_human(text):
  d=convs.find_one_and_update({'_id':ObjectId(cid),'status':{'$in':['bot_active','waiting_human']}},{'$set':{'status':'waiting_human','updated_at':now()}},return_document=ReturnDocument.AFTER)
  s=save(cid,'bot','Sure. I’m connecting you with a KoraLink support agent. Please wait while an agent joins the conversation.')
  emit_conv(cid,'new_message',mj(s)); socketio.emit('queue_updated',{},room='agents')
  return jsonify(customer_id=cust,conversation=cj(d),mode='waiting_human',response=s['message'],images=[],step_images={})
 if d['status']=='waiting_human':
  s=save(cid,'bot','Your request is in the support queue. An agent will join shortly.'); emit_conv(cid,'new_message',mj(s)); return jsonify(customer_id=cust,conversation=cj(d),mode='waiting_human',response=s['message'],images=[],step_images={})
 try:
  if lang=='rw':
   from deep_translator import GoogleTranslator
   q=GoogleTranslator(source='rw',target='en').translate(text); result=scp.answer_finder(q); answer=result['answer']; images=result['images']; steps=result['step_images']; answer=GoogleTranslator(source='en',target='rw').translate(answer)
  else:
   result=scp.answer_finder(text); answer=result['answer']; images=result['images']; steps=result['step_images']
  answer=answer.replace('â€“','-').replace('â€”','-').replace('â€','')
 except Exception:
  app.logger.exception('Chatbot error'); return jsonify(error='Chatbot processing failed'),500
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
@app.get('/api/agent/queue')
def queue():
 a,e=req_agent()
 if e:return e
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
 return jsonify(conversation=cj(d),messages=[mj(x) for x in msgs.find({'conversation_id':cid}).sort('created_at',1).limit(500)])
@app.post('/api/agent/conversation/<cid>/claim')
def claim(cid):
 a,e=req_agent()
 if e:return e
 d=convs.find_one_and_update({'_id':ObjectId(cid),'status':'waiting_human','agent_id':None},{'$set':{'status':'human_active','agent_id':str(a['_id']),'updated_at':now()}},return_document=ReturnDocument.AFTER)
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
@app.post('/api/agent/conversation/<cid>/close')
def close(cid):
 a,e=req_agent()
 if e:return e
 d=convs.find_one_and_update({'_id':ObjectId(cid),'status':'human_active','agent_id':str(a['_id'])},{'$set':{'status':'closed','closed_at':now(),'updated_at':now()}},return_document=ReturnDocument.AFTER)
 if not d:return jsonify(error='Conversation not found or not owned by you'),404
 m=save(cid,'system','The support conversation has been closed. You can start a new chat if you need more help.'); emit_conv(cid,'conversation_closed',{'conversation':cj(d)}); emit_conv(cid,'new_message',mj(m)); socketio.emit('queue_updated',{},room='agents'); return jsonify(conversation=cj(d))

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

@app.route("/")
def home():
    return send_file("index.html")
@app.route("/chat", methods=["POST"])
def legacy_chat():
    try:
        data = request.get_json() or {}

        message = data.get("message", "").strip()
        language = data.get("language", "en")

        if not message:
            return jsonify({
                "error": "Message is required"
            }), 400

        # Kinyarwanda → English
        if language == "rw":
            english_message = GoogleTranslator(
                source="rw",
                target="en"
            ).translate(message)

            result = scp.answer_finder(english_message)

            answer = result.get("answer", "")
            images = result.get("images", [])
            step_images = result.get("step_images", [])

            # English → Kinyarwanda
            answer = GoogleTranslator(
                source="en",
                target="rw"
            ).translate(answer)

        else:
            result = scp.answer_finder(message)

            answer = result.get("answer", "")
            images = result.get("images", [])
            step_images = result.get("step_images", [])

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
