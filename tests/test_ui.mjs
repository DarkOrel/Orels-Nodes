import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
let extension, calls=[], timers=new Map(), serial=0;
class Element {
    constructor(tag){this.tagName=tag;this.style={};this.children=[];this.listeners={};this.value='';this.disabled=false;}
    append(...items){this.children.push(...items);}
    setAttribute(k,v){this[k]=v;}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    async dispatch(type,extra={}){
        const e={preventDefault(){},stopPropagation(){},...extra};
        for(const fn of this.listeners[type]||[])await fn(e);
        if(type==='click' && this.onclick)await this.onclick(e);
    }
    click(){return this.dispatch('click');}
    showModal(){this.open=true;}
    close(){this.open=false;}
    remove(){this.removed=true;}
}
const body=new Element('body');
const context={
 document:{createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),body},
 FormData,
 app:{registerExtension:x=>extension=x},
 api:{fetchApi:async(url,options)=>{
    const isBinary=options?.body instanceof Blob;
    const data=isBinary ? options.body : options ? JSON.parse(options.body) : null;
    calls.push({url,data});
    if(url.endsWith('/upload/init'))return {ok:true,json:async()=>({status:'Ready',upload_id:'upload-1',chunk_size:2})};
    if(url.endsWith('/upload/chunk'))return {ok:true,json:async()=>({status:'Uploading',received:Number(options.headers['X-Orels-Upload-Offset'])+options.body.size,size:4})};
    return {ok:true,json:async()=>({status:'Installed',source:'session',message:'Complete',path:'/models/test'})};
 }},
 setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},
 clearTimeout:id=>timers.delete(id),
};
const graphSource=fs.readFileSync(new URL('../web/control_graph.js',import.meta.url),'utf8').replace('export function','function');
const source=fs.readFileSync(new URL('../web/orels-v05.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
vm.runInNewContext(graphSource+'\n'+source,context);
function nodeClass(type){return class {
    constructor(){this.type=type;this.id=42;this.inputs=[];this.outputs=[];this.size=[300,100];
        this.widgets=type==='OrelsModelDownload' ? ['repo_id','filename','category'].map((name,i)=>({name,type:'text',value:['owner/repo','file.safetensors','vae'][i]})) : [];
    }
    addDOMWidget(name,type,element,options){const w={name,type,element,options};this.widgets.push(w);return w;}
    setDirtyCanvas(){}
    setSize(size){this.size=size;}
};}
const Model=nodeClass('OrelsModelDownload');
await extension.beforeRegisterNodeDef(Model,{name:'OrelsModelDownload'});
const n=new Model();n.onNodeCreated();n.inputs=[{name:'download_control'}];
const widget=(node,name)=>node.widgets.find(w=>w.name===name);
await widget(n,'Download model').element.click();
assert.equal(calls[0].url,'/orels-nodes/models/download');
assert.equal(calls[0].data.filename,'file.safetensors');
assert.equal(widget(n,'Status').element.children[1].textContent,'Installed');
assert.equal(widget(n,'Status').options.serialize,false);
assert.equal(widget(n,'Download model').element.style.minHeight,'42px');
assert.equal(widget(n,'Download model').element.disabled,false);
await widget(n,'Check status').element.click();
assert.equal(calls[1].url,'/orels-nodes/models/status');
assert.equal(n.outputs.length,0);
assert.equal(widget(n,'revision'),undefined);
assert.equal(widget(n,'subfolder'),undefined);
n.onRemoved();assert.equal(timers.size,0);

const Batch=nodeClass('OrelsDownloadAll');
await extension.beforeRegisterNodeDef(Batch,{name:'OrelsDownloadAll'});
const b=new Batch();b.outputs=[{links:[1,2]}];
b.graph={links:{1:{target_id:42,target_slot:0},2:{target_id:42,target_slot:0}},getNodeById:()=>n};
b.onNodeCreated();extension.nodeCreated(b);
assert.equal(b.widgets.filter(w=>w.name==='Download All').length,1);
await widget(b,'Download All').element.click();
assert.equal(calls.find(c=>c.url==='/orels-nodes/models/batch'&&c.data).data.models.length,1);
assert(b.size[1]>=240);
b.onRemoved();

// Nested native Subgraphs: select only the connected socket, skip muted branch.
const ignored=new Model();ignored.id=43;
const nestedGraph={links:new Map([[8,{target_id:42,target_slot:0}],[9,{target_id:43,target_slot:0}]]),getNodeById:id=>id===42?n:ignored};
const inner={id:70,mode:0,inputs:[{_subgraphSlot:{linkIds:[8]}},{_subgraphSlot:{linkIds:[9]}}],subgraph:nestedGraph};
const middle={getLink:id=>({target_id:70,target_slot:0}),getNodeById:()=>inner};
const outer={id:80,mode:0,inputs:[{_subgraphSlot:{linkIds:[7]}}],subgraph:middle};
b.graph={getLink:()=>({target_id:80,target_slot:0}),getNodeById:()=>outer};b.outputs=[{links:[6]}];
assert.equal(context.connectedModels(b).length,1);
assert.equal(context.connectedModels(b)[0],n);
outer.mode=2;assert.equal(context.connectedModels(b).length,0);outer.mode=0;
inner.inputs[0]._subgraphSlot={linkIds:[8,8]};assert.equal(context.connectedModels(b).length,1);
// Positional slot fallback on older native-subgraph frontends.
delete outer.inputs[0]._subgraphSlot;middle.inputNode={slots:[{linkIds:[7]}]};
assert.equal(context.connectedModels(b).length,1);

const Token=nodeClass('OrelsHFToken');await extension.beforeRegisterNodeDef(Token,{name:'OrelsHFToken'});
const t=new Token();t.onNodeCreated();extension.nodeCreated(t);
assert.equal(t.outputs.length,0);
assert.equal(t.size.join(','),'460,240');
t.size=[900,900];t.onConfigure();assert.equal(t.size.join(','),'460,240');
assert.equal(t.widgets.filter(w=>w.name==='Set / change Hugging Face token').length,1);
await widget(t,'Set / change Hugging Face token').element.click();
const dialog=body.children.at(-1);assert(dialog.open);
const password=dialog.children.find(e=>e.type==='password');password.value='hf_test_secret';
const actions=dialog.children.at(-1);
await actions.children.find(e=>e.textContent==='Save token').click();
assert.equal(password.value,'');
await actions.children.find(e=>e.textContent==='Remove saved/session token').click();
assert(calls.some(c=>c.data?.action==='clear'));
await actions.children.find(e=>e.textContent==='Close').click();assert(dialog.removed);
assert(!JSON.stringify(t.widgets).includes('hf_test_secret'));

const Upload=nodeClass('OrelsLoraUpload');await extension.beforeRegisterNodeDef(Upload,{name:'OrelsLoraUpload'});
const u=new Upload();u.onNodeCreated();extension.nodeCreated(u);
const zone=widget(u,'Drop LoRA').element;
await zone.dispatch('drop',{dataTransfer:{files:[new File(['test'],'check.safetensors')]}});
assert(calls.some(c=>c.url==='/orels-nodes/upload/init'));
assert.equal(calls.filter(c=>c.url==='/orels-nodes/upload/chunk').length,2);
assert(calls.some(c=>c.url==='/orels-nodes/upload/finish'));
assert(widget(u,'Upload status').element.children[1].textContent.includes('Uploads complete'));
const before=calls.length;
await zone.dispatch('drop',{dataTransfer:{files:[new File(['bad'],'bad.ckpt')]}});
assert.equal(calls.length,before);
assert(widget(u,'Upload status').element.children[1].textContent.includes('only .safetensors'));
u.onRemoved();
console.log('UI checks passed: fixed layout, removed ports/advanced fields, nested Subgraph controls, token save/remove, and chunked LoRA drop.');
// Ensure packaged subgraph wiring resolves Download All to all three model nodes.
const example=JSON.parse(fs.readFileSync(new URL('../examples/subgraph-download-control.json',import.meta.url),'utf8'));
const definition=example.definitions.subgraphs[0];
const native={
    inputNode:{slots:definition.inputs},
    links:new Map(definition.links.map(l=>[l.id,l])),
    getNodeById:id=>definition.nodes.find(n=>n.id===id),
};
const outerExample=example.nodes.find(n=>n.type===definition.id);outerExample.subgraph=native;
const graphExample={getLink:id=>{const l=example.links.find(l=>l[0]===id);return {target_id:l[3],target_slot:l[4]};},getNodeById:id=>example.nodes.find(n=>n.id===id)};
const c=example.nodes.find(n=>n.type==='OrelsDownloadAll');c.graph=graphExample;
assert.equal(context.connectedModels(c,'download_control').length,3);
console.log('Packaged Subgraph control resolves all three models.');
