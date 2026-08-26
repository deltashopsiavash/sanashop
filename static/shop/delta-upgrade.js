(function(){
  'use strict';

  function initTypewriter(){
    document.querySelectorAll('[data-typewriter]').forEach(function(el){
      const text=el.dataset.text||el.textContent||'';
      if(!text)return;
      el.textContent='';
      let i=0, deleting=false;
      function tick(){
        if(!deleting){
          i=Math.min(text.length,i+1);
          el.textContent=text.slice(0,i);
          if(i>=text.length){deleting=true;return setTimeout(tick,2800)}
          return setTimeout(tick,55+Math.random()*45);
        }
        i=Math.max(0,i-1);
        el.textContent=text.slice(0,i);
        if(i<=0){deleting=false;return setTimeout(tick,500)}
        setTimeout(tick,22);
      }
      setTimeout(tick,250);
    });
  }

  function initBanner(){
    const root=document.getElementById('home-banner-carousel'),track=document.getElementById('home-banner-track');
    if(!root||!track)return;
    const slides=[...track.querySelectorAll('[data-banner-slide]')],dots=[...root.querySelectorAll('[data-banner-dot]')];
    const prev=document.getElementById('home-banner-prev'),next=document.getElementById('home-banner-next');
    if(!slides.length)return;
    let index=0,timer=null,startX=0,lastX=0,dragging=false,moved=false,suppressClick=false;
    const autoplay=Math.max(2500,parseInt(root.dataset.autoplayMs||'4500',10));
    const normalize=i=>(i+slides.length)%slides.length;
    function render(animate=true,dragPx=0){
      track.style.transition=animate?'transform .55s cubic-bezier(.22,.61,.36,1)':'none';
      const base=index*100;
      track.style.transform=dragPx?`translate3d(calc(-${base}% + ${dragPx}px),0,0)`:`translate3d(-${base}%,0,0)`;
      dots.forEach((dot,i)=>dot.classList.toggle('active',i===index));
    }
    function stop(){if(timer){clearInterval(timer);timer=null}}
    function start(){if(slides.length<2||dragging)return;stop();timer=setInterval(()=>{index=normalize(index+1);render(true)},autoplay)}
    function go(i){index=normalize(i);render(true);start()}
    if(prev)prev.addEventListener('click',()=>go(index-1));
    if(next)next.addEventListener('click',()=>go(index+1));
    dots.forEach(dot=>dot.addEventListener('click',()=>go(parseInt(dot.dataset.bannerDot,10))));
    root.addEventListener('pointerdown',e=>{if(slides.length<2||e.button>0)return;dragging=true;moved=false;startX=lastX=e.clientX;stop();root.classList.add('is-dragging');try{root.setPointerCapture(e.pointerId)}catch(_){}});
    root.addEventListener('pointermove',e=>{if(!dragging)return;lastX=e.clientX;const dx=lastX-startX;if(Math.abs(dx)>5)moved=true;render(false,dx)});
    function finish(e){if(!dragging)return;const dx=lastX-startX;dragging=false;root.classList.remove('is-dragging');try{root.releasePointerCapture(e.pointerId)}catch(_){}if(Math.abs(dx)>55)index=normalize(index+(dx<0?1:-1));suppressClick=moved;render(true);start();setTimeout(()=>{suppressClick=false},90)}
    root.addEventListener('pointerup',finish);root.addEventListener('pointercancel',finish);
    root.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopPropagation()}},true);
    root.addEventListener('mouseenter',stop);root.addEventListener('mouseleave',()=>{if(!dragging)start()});
    document.addEventListener('visibilitychange',()=>{document.hidden?stop():start()});
    render(false);start();
  }

  function initLocations(){
    const script=document.getElementById('iran-locations');
    const provinceInput=document.getElementById('province-input'),cityInput=document.getElementById('city-input');
    if(!script||!provinceInput||!cityInput)return;
    let locations={};try{locations=JSON.parse(script.textContent||'{}')}catch(_){return}
    const provinceTrigger=document.getElementById('province-trigger'),cityTrigger=document.getElementById('city-trigger');
    const provincePanel=document.getElementById('province-panel'),cityPanel=document.getElementById('city-panel');
    const provinceSearch=document.getElementById('province-search'),citySearch=document.getElementById('city-search');
    const provinceOptions=document.getElementById('province-options'),cityOptions=document.getElementById('city-options');
    const provinceLabel=document.getElementById('province-label'),cityLabel=document.getElementById('city-label');
    const normalize=v=>String(v||'').trim().toLocaleLowerCase('fa-IR').replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,' ');
    const closeAll=()=>{[provincePanel,cityPanel].forEach(x=>x&&x.classList.remove('open'));[provinceTrigger,cityTrigger].forEach(x=>x&&x.setAttribute('aria-expanded','false'))};
    const filter=(box,term)=>{if(!box)return;const q=normalize(term);box.querySelectorAll('button[data-value]').forEach(btn=>btn.hidden=!!(q&&!normalize(btn.dataset.value).includes(q)))};
    function makeCities(){
      const cities=locations[provinceInput.value]||[];cityOptions.innerHTML='';
      cities.forEach(name=>{const btn=document.createElement('button');btn.type='button';btn.dataset.value=name;btn.textContent=name;if(name===cityInput.value)btn.classList.add('selected');cityOptions.appendChild(btn)});
      cityTrigger.disabled=!cities.length;
      if(!cities.length)cityLabel.textContent='شهر را وارد کنید';
    }
    function open(panel,trigger,search){if(!panel||!trigger||trigger.disabled)return;const was=panel.classList.contains('open');closeAll();if(was)return;panel.classList.add('open');trigger.setAttribute('aria-expanded','true');if(search){search.value='';filter(panel,'');setTimeout(()=>search.focus(),30)}}
    provinceTrigger.addEventListener('click',()=>open(provincePanel,provinceTrigger,provinceSearch));
    cityTrigger.addEventListener('click',()=>open(cityPanel,cityTrigger,citySearch));
    provinceSearch.addEventListener('input',()=>filter(provinceOptions,provinceSearch.value));
    citySearch.addEventListener('input',()=>filter(cityOptions,citySearch.value));
    provinceOptions.addEventListener('click',e=>{const btn=e.target.closest('button[data-value]');if(!btn)return;const changed=provinceInput.value!==btn.dataset.value;provinceInput.value=btn.dataset.value;provinceLabel.textContent=btn.dataset.value;provinceOptions.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===btn));if(changed){cityInput.value='';cityLabel.textContent='یک شهر انتخاب کنید'}makeCities();closeAll()});
    cityOptions.addEventListener('click',e=>{const btn=e.target.closest('button[data-value]');if(!btn)return;cityInput.value=btn.dataset.value;cityLabel.textContent=btn.dataset.value;cityOptions.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===btn));closeAll()});
    document.addEventListener('click',e=>{if(!e.target.closest('.smart-location-field'))closeAll()});
    makeCities();
  }

  function initReservationTimers(){
    document.querySelectorAll('[data-reservation-seconds]').forEach(el=>{
      let seconds=Math.max(0,parseInt(el.dataset.reservationSeconds||'0',10));
      const render=()=>{const m=Math.floor(seconds/60),s=seconds%60;el.textContent=seconds>0?`⏳ ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:'⛔ زمان رزرو تمام شد';el.classList.toggle('expired',seconds<=0)};
      render();if(seconds<=0)return;
      const timer=setInterval(()=>{seconds=Math.max(0,seconds-1);render();if(seconds<=0){clearInterval(timer);document.querySelectorAll('[data-disable-on-expire]').forEach(x=>x.disabled=true)}},1000);
    });
  }

  function formatMoneyInputs(){
    document.querySelectorAll('[data-money-input]').forEach(input=>{
      input.addEventListener('input',()=>{const pos=input.selectionStart;const raw=input.value.replace(/[^0-9]/g,'');input.dataset.rawValue=raw;input.value=raw?Number(raw).toLocaleString('en-US'):'';try{input.setSelectionRange(pos,pos)}catch(_){}});
      const form=input.form;if(form)form.addEventListener('submit',()=>{input.value=(input.dataset.rawValue||input.value).replace(/,/g,'')});
    });
  }

  document.addEventListener('DOMContentLoaded',()=>{initTypewriter();initBanner();initLocations();initReservationTimers();formatMoneyInputs()});
})();
