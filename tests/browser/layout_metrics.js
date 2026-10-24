(() => {
  const width = document.documentElement.clientWidth;
  const rect = el => {const r=el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const label = el => (el.innerText || el.getAttribute('aria-label') || el.name || '').trim().replace(/\s+/g,' ').slice(0,100);
  const activeDialog = document.querySelector('.modal.show');
  const controls = [...(activeDialog || document).querySelectorAll('.btn, input:not([type=hidden]), select, textarea')].filter(visible);
  const clippedRect = element => {
    const raw=rect(element); const result={left:Math.max(0,raw.left),right:Math.min(width,raw.right),top:Math.max(0,raw.top),bottom:Math.min(innerHeight,raw.bottom)};
    for(let parent=element.parentElement;parent;parent=parent.parentElement){
      const style=getComputedStyle(parent),bounds=rect(parent);
      if(['auto','scroll','hidden','clip'].includes(style.overflowX)){result.left=Math.max(result.left,bounds.left);result.right=Math.min(result.right,bounds.right);}
      if(['auto','scroll','hidden','clip'].includes(style.overflowY)){result.top=Math.max(result.top,bounds.top);result.bottom=Math.min(result.bottom,bounds.bottom);}
    }
    return result;
  };
  const overlaps=[];
  for(let i=0;i<controls.length;i++) for(let j=i+1;j<controls.length;j++) {
    const a=controls[i],b=controls[j]; if(a.contains(b)||b.contains(a)) continue;
    const ar=clippedRect(a),br=clippedRect(b);
    const intersection=Math.max(0,Math.min(ar.right,br.right)-Math.max(ar.left,br.left))*Math.max(0,Math.min(ar.bottom,br.bottom)-Math.max(ar.top,br.top));
    if(intersection>12) overlaps.push({a:label(a),b:label(b),intersection:Math.round(intersection)});
  }
  const tables=[...document.querySelectorAll('table')].filter(visible).map((table,index)=>{
    const container=table.closest('.table-responsive') || table.parentElement;
    const r=rect(table),c=rect(container);
    return {index:index+1,headers:[...table.querySelectorAll('th')].map(label),width:Math.round(r.width),containerWidth:Math.round(c.width),overflow:Math.max(0,Math.round(table.scrollWidth-container.clientWidth)),hasScrollContainer:!!table.closest('.table-responsive'),containerOverflow:getComputedStyle(container).overflowX,offscreenCells:[...table.querySelectorAll('tbody tr:first-child td')].filter(el=>rect(el).right>Math.min(width,c.right)+2).map(label)};
  });
  const compressedControls=controls.filter(el=>rect(el).width<48 && !['checkbox','radio'].includes(el.type)).map(el=>({label:label(el),...rect(el)}));
  const clippedButtons=[...document.querySelectorAll('.btn')].filter(visible).filter(el=>el.scrollWidth>el.clientWidth+2).map(el=>({label:label(el),width:rect(el).width,scrollWidth:el.scrollWidth}));
  const offscreen=[...document.querySelectorAll('#main-content *')].filter(visible).filter(el=>rect(el).right>width+2 && !el.closest('.table-responsive')).slice(0,18).map(el=>({tag:el.tagName,cls:String(el.className),label:label(el),right:Math.round(rect(el).right)}));
  return {title:document.title,url:location.pathname,clientWidth:width,innerWidth,pageWidth:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),pageHeight:document.documentElement.scrollHeight,tables,overlaps:overlaps.slice(0,20),clippedButtons,compressedControls:compressedControls.slice(0,12),offscreen,mainText:document.querySelector('#main-content')?.innerText.slice(0,180),modal:activeDialog?{dialog:rect(activeDialog.querySelector('.modal-content')),footer:rect(activeDialog.querySelector('.modal-footer'))}:null};
})();
