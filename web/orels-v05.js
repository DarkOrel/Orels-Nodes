import { app } from '../../scripts/app.js';
import { api } from '../../scripts/api.js';
import { connectedModels } from './control_graph.js';

function display(node, name, initial = '') {
    const element = document.createElement('div');
    Object.assign(element.style, {padding:'6px 10px', color:'#ddd', background:'#26282b',
        borderRadius:'6px', fontSize:'12px', whiteSpace:'pre-wrap', overflowWrap:'anywhere',
        overflow:'auto', userSelect:'text', boxSizing:'border-box'});
    const label = document.createElement('strong');
    label.textContent = name + ': ';
    const text = document.createElement('span');
    element.append(label, text);
    const height = name.includes('Destination') || name.includes('Details') || name.includes('status') ? 64 : 38;
    const widget = node.addDOMWidget(name, 'orels_readonly', element, {serialize:false, getMinHeight:()=>height, getMaxHeight:()=>height});
    if (widget) widget.computeSize = () => [0,height];
    const state = {set value(value) { text.textContent = value; }};
    state.value = initial;
    return state;
}

async function tokenDialog() {
    const dialog = document.createElement('dialog');
    Object.assign(dialog.style, {maxWidth:'480px', width:'90%', background:'#25272b', color:'#eee',
        border:'1px solid #666', borderRadius:'12px', padding:'22px'});
    const title = document.createElement('h3'); title.textContent = 'Hugging Face token — this server';
    const info = document.createElement('p'); info.textContent = 'Checking configuration…';
    const link = document.createElement('a'); link.textContent = 'Create a read token on Hugging Face';
    link.href = 'https://huggingface.co/settings/tokens'; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const input = document.createElement('input'); input.type = 'password'; input.placeholder = 'hf_…';
    input.autocomplete = 'off'; input.setAttribute('aria-label', 'Hugging Face token');
    Object.assign(input.style, {display:'block', width:'100%', margin:'16px 0', boxSizing:'border-box'});
    const remember = document.createElement('input'); remember.type = 'checkbox';
    const label = document.createElement('label'); label.append(remember, document.createTextNode(' Remember on this server'));
    const help = document.createElement('p');
    help.textContent = 'Shared by all Orel’s Nodes on this server. Never included in the workflow. Remember stores a private-permission file on the server, without encryption. Otherwise it lasts until ComfyUI restarts. Accept gated repository terms separately. Use HTTPS for remote servers.';
    const actions = document.createElement('div');
    const close = () => { input.value = ''; dialog.close(); dialog.remove(); };
    const showStatus = value => { info.textContent = 'Token: ' + value.source + '. Saving does not verify repository access.'; };
    async function send(data) {
        try {
            const response = await api.fetchApi('/orels-nodes/credentials', {method:'POST',
                headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || 'Could not update token.');
            input.value = ''; showStatus(result);
        } catch (error) { info.textContent = error.message; }
    }
    for (const [name, callback] of [
        ['Save token', () => send({token:input.value.trim(), remember:remember.checked})],
        ['Remove saved/session token', () => send({action:'clear'})],
        ['Close', close],
    ]) {
        const button = document.createElement('button'); button.textContent = name;
        button.onclick = callback;
        Object.assign(button.style,{margin:'5px 0',padding:'10px 14px',minHeight:'42px',width:'100%',
            cursor:'pointer',border:'1px solid #727880',borderRadius:'7px',color:'#fff',background:'#3b414b',pointerEvents:'auto'});
        actions.append(button);
    }
    dialog.append(title, info, link, input, label, help, actions);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    document.body.append(dialog); dialog.showModal();
    try {
        const response = await api.fetchApi('/orels-nodes/credentials');
        const value = await response.json();
        if (!response.ok) throw new Error();
        showStatus(value);
    } catch (_) { info.textContent = 'Cannot read token settings. Check the server connection.'; }
}

const modelConfig = node => {
    const fields=['repo_id','filename','category'];
    if(node.inputs?.some(input=>fields.includes(input.name) && input.link != null))
        throw new Error('Keep model settings inside Model\'s Download; expose only download_control.');
    return Object.fromEntries(fields.map(name => [name,node.widgets.find(w=>w.name===name)?.value]));
};

function setupBatch(node) {
    if (node._orelsBatchReady) return;
    node._orelsBatchReady=true;
    const state = display(node, 'Batch status', 'Connect download_models → download_control, including through a Subgraph.');
    let timer, removed = false;
    async function poll() {
        try {
            const response = await api.fetchApi('/orels-nodes/models/batch');
            const value = await response.json();
            if (removed) return;
            state.value = value.status + ': ' + value.message;
            node.setDirtyCanvas(true, true);
            if (value.status === 'Downloading') timer = setTimeout(poll, 2000);
        } catch (_) { if (!removed) state.value = 'Cannot reach server. Click Check batch status.'; }
    }
    buttonWidget(node, 'Download All', null, async () => {
        try {
            const models = connectedModels(node).map(modelConfig);
            if (!models.length) { state.value = "Connect at least one active Model's Download (directly or through Subgraph inputs)."; return; }
            const response = await api.fetchApi('/orels-nodes/models/batch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({models})});
            const value = await response.json();
            if (removed) return;
            state.value = value.status + ': ' + value.message;
            if (response.ok) { clearTimeout(timer); await poll(); }
        } catch (error) { if (!removed) state.value = error.message || 'Connection interrupted. Check batch status before retrying.'; }
    }, {serialize:false});
    buttonWidget(node, 'Check batch status', null, () => { clearTimeout(timer); return poll(); }, {serialize:false});
    const old = node.onRemoved;
    node.onRemoved = function () { removed=true; clearTimeout(timer); old?.apply(this,arguments); };
    node.size[0] = Math.max(node.size[0], 420);
    keepLayout(node, 'Download All', 420, 240);
}

function keepLayout(node, title, width, height) {
    if (!node.title) node.title=title;
    const previous=node.onConfigure;
    node.onConfigure=function(){
        previous?.apply(this,arguments);
        if (!this.title) this.title=title;
        resize(this,width,height);
    };
    resize(node,width,height);
}

function resize(node, width, height) {
    node.setSize?.([width,height]);
    node.size[0] = width;
    node.size[1] = height;
    node.setDirtyCanvas(true,true);
}

function buttonWidget(node, name, unused, callback) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = name;
    Object.assign(button.style,{width:'100%',height:'42px',minHeight:'42px',boxSizing:'border-box',
        cursor:'pointer',pointerEvents:'auto',background:'#3e4859',color:'#fff',border:'1px solid #74829a',
        borderRadius:'7px',fontSize:'13px',fontWeight:'600'});
    button.addEventListener('pointerdown',e=>e.stopPropagation());
    button.addEventListener('click',async e=>{
        e.preventDefault(); e.stopPropagation();
        if (button.disabled) return;
        button.disabled=true;
        try { await callback(); } finally { button.disabled=false; }
    });
    const widget = node.addDOMWidget(name,'orels_button',button,{serialize:false,getMinHeight:()=>44,getMaxHeight:()=>44});
    if (widget) widget.computeSize=()=>[0,44];
    return button;
}

function setupToken(node) {
    if (node._orelsTokenReady) return;
    node._orelsTokenReady=true;
    const state=display(node,'Token status','Uses HF_TOKEN automatically when available.');
    async function check() {
        try {
            const response=await api.fetchApi('/orels-nodes/credentials');
            const result=await response.json();
            if (!response.ok) throw new Error(result.message);
            state.value=`Token: ${result.source}. Token is shared by every Model's Download on this server.`;
        } catch(error) { state.value=error.message || 'Could not read token status.'; }
    }
    buttonWidget(node,'Set / change Hugging Face token',null,tokenDialog);
    buttonWidget(node,'Check token / connections',null,check);
    keepLayout(node, 'Hugging Face Token',460,240);
}

function setupUpload(node) {
    if (node._orelsUploadReady) return;
    node._orelsUploadReady=true;
    const state=display(node,'Upload status','Drop a .safetensors LoRA below.');
    const target=display(node,'Destination (automatic)','ComfyUI registered loras folder');
    const area=document.createElement('div');
    area.textContent='Drop LoRA files here';
    Object.assign(area.style,{border:'2px dashed #85a9e0',borderRadius:'10px',padding:'18px',boxSizing:'border-box',
        minHeight:'80px',background:'#273346',color:'#fff',textAlign:'center',pointerEvents:'auto'});
    const picker=document.createElement('input'); picker.type='file';picker.accept='.safetensors';picker.multiple=true;picker.style.display='none';
    area.append(picker);
    let busy=false, removed=false;
    async function upload(files) {
        if (busy) { state.value='An upload is already running. Wait for it to finish.'; return; }
        busy=true;
        const errors=[];
        try {
            for (const [index,file] of [...files].entries()) {
                if (removed) break;
                if (!file.name.toLowerCase().endsWith('.safetensors')) { errors.push(`${file.name}: only .safetensors is supported.`); continue; }
                if (file.size > 8*1024**3) { errors.push(`${file.name}: exceeds 8 GiB.`); continue; }
                state.value=`Uploading ${index+1}/${files.length}: ${file.name}…`;
                let uploadId;
                try {
                    let response=await api.fetchApi('/orels-nodes/upload/init',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,size:file.size})});
                    let result=await response.json();
                    if(!response.ok)throw new Error(result.message||'Could not start upload.');
                    uploadId=result.upload_id;
                    const chunkSize=result.chunk_size;
                    for(let offset=0;offset<file.size;offset+=chunkSize){
                        const chunk=file.slice(offset,Math.min(offset+chunkSize,file.size));
                        response=await api.fetchApi('/orels-nodes/upload/chunk',{method:'POST',headers:{
                            'Content-Type':'application/octet-stream','X-Orels-Upload-ID':uploadId,
                            'X-Orels-Upload-Offset':String(offset)},body:chunk});
                        result=await response.json();
                        if(!response.ok)throw new Error(result.message||'A file chunk was rejected.');
                        state.value=`Uploading ${index+1}/${files.length}: ${file.name} — ${Math.floor(result.received/result.size*100)}%`;
                    }
                    response=await api.fetchApi('/orels-nodes/upload/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_id:uploadId})});
                    result=await response.json();
                    if(!response.ok)throw new Error(result.message||'Could not finish upload.');
                    if (!removed) { state.value=result.message;target.value=result.path; }
                } catch(error) {
                    if(uploadId)api.fetchApi('/orels-nodes/upload/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_id:uploadId})}).catch(()=>{});
                    errors.push(`${file.name}: ${error.message}`);
                }
            }
            if (!removed) state.value=errors.length ? errors.join('\n') : 'Uploads complete. Refresh model lists, then select your LoRA in its loader.';
        } finally { busy=false;picker.value=''; }
    }
    for (const type of ['dragenter','dragover','dragleave','drop']) area.addEventListener(type,e=>{e.preventDefault();e.stopPropagation();});
    area.addEventListener('dragover',e=>{ if(e.dataTransfer)e.dataTransfer.dropEffect='copy'; });
    area.addEventListener('drop',e=>upload(e.dataTransfer?.files || []));
    picker.addEventListener('change',()=>upload(picker.files || []));
    const widget=node.addDOMWidget('Drop LoRA','orels_dropzone',area,{serialize:false,getMinHeight:()=>90,getMaxHeight:()=>90});
    if(widget)widget.computeSize=()=>[0,90];
    buttonWidget(node,'Choose LoRA files…',null,()=>picker.click());
    const old=node.onRemoved;node.onRemoved=function(){removed=true;old?.apply(this,arguments);};
    keepLayout(node, 'LoRA Upload',460,330);
}

app.registerExtension({
    name: 'OrelsNodes.Models.v05',
    nodeCreated(node) {
        const type=node.comfyClass || node.type;
        if(type==='OrelsDownloadAll')setupBatch(node);
        if(type==='OrelsHFToken')setupToken(node);
        if(type==='OrelsLoraUpload')setupUpload(node);
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (['OrelsHFToken','OrelsLoraUpload'].includes(nodeData.name)) {
            const old=nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated=function(){
                const result=old?.apply(this,arguments);
                (nodeData.name==='OrelsHFToken' ? setupToken : setupUpload)(this);
                return result;
            };
            return;
        }
        if (nodeData.name === 'OrelsDownloadAll') {
            const old = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () { const result = old?.apply(this, arguments); setupBatch(this); return result; };
            return;
        }
        if (nodeData.name !== 'OrelsModelDownload') return;
        const previous = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = previous?.apply(this, arguments);
            const node = this;
            let timer, removed = false, generation = 0;
            const status = display(node, 'Status', 'Checking…');
            const detail = display(node, 'Details');
            const destination = display(node, 'Destination (automatic)');
            const config = () => modelConfig(node);
            async function refresh(start = false) {
                clearTimeout(timer);
                const ticket = ++generation;
                try {
                    const data = config();
                    const response = await api.fetchApi(`/orels-nodes/models/${start ? 'download' : 'status'}`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
                    });
                    const value = await response.json();
                    if (removed || ticket !== generation) return;
                    status.value = value.status;
                    detail.value = value.message || '';
                    destination.value = value.path || '';
                    node.setDirtyCanvas(true, true);
                } catch (error) {
                    if (removed || ticket !== generation) return;
                    status.value = 'Error';
                    detail.value = error.message || 'Cannot reach ComfyUI. Reconnect and check status; the server may still be downloading.';
                    node.setDirtyCanvas(true, true);
                }
                if (!removed && ticket === generation) timer = setTimeout(() => refresh(), 3000);
            }
            buttonWidget(node, 'Download model', null, () => refresh(true), { serialize: false });
            buttonWidget(node, 'Check status', null, () => refresh(), { serialize: false });
            for (const w of node.widgets.filter(w => ['repo_id','filename','category'].includes(w.name))) {
                const old = w.callback;
                w.callback = function () { old?.apply(this, arguments); refresh(); };
            }
            const oldRemove = node.onRemoved;
            node.onRemoved = function () { removed = true; generation++; clearTimeout(timer); oldRemove?.apply(this, arguments); };
            node.size[0] = Math.max(node.size[0], 480);
            keepLayout(node, "Model's Download", 480, 430);
            timer = setTimeout(() => refresh(), 250);
            return result;
        };
    },
});
