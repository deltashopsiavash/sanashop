(function(){
  'use strict';

  function initStories(){
    const dialog=document.getElementById('storyDialog');
    if(!dialog)return;
    const mediaBox=dialog.querySelector('[data-story-media-box]');
    const title=dialog.querySelector('[data-story-title]');
    const buy=dialog.querySelector('[data-story-buy]');
    const expire=dialog.querySelector('[data-story-expire]');
    const close=dialog.querySelector('[data-story-close]');

    function stopMedia(){
      const video=mediaBox.querySelector('video');
      if(video){try{video.pause()}catch(_){}}
      mediaBox.innerHTML='';
    }
    function openStory(btn){
      stopMedia();
      const type=btn.dataset.storyType||'image';
      const src=btn.dataset.storySrc||'';
      if(type==='video'){
        const video=document.createElement('video');
        video.src=src;video.controls=true;video.autoplay=true;video.playsInline=true;video.preload='metadata';
        mediaBox.appendChild(video);
      }else{
        const img=document.createElement('img');img.src=src;img.alt=btn.dataset.storyTitle||'';mediaBox.appendChild(img);
      }
      title.textContent=btn.dataset.storyTitle||'';
      buy.href=btn.dataset.storyTarget||'#';
      const seconds=parseInt(btn.dataset.storyRemaining||'0',10);
      expire.dataset.remaining=String(Math.max(0,seconds));
      if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
    }
    document.querySelectorAll('[data-story-open]').forEach(btn=>btn.addEventListener('click',()=>openStory(btn)));
    if(close)close.addEventListener('click',()=>{stopMedia();dialog.close()});
    dialog.addEventListener('click',e=>{if(e.target===dialog){stopMedia();dialog.close()}});
    dialog.addEventListener('close',stopMedia);

    setInterval(()=>{
      if(!expire.dataset.remaining)return;
      let seconds=Math.max(0,parseInt(expire.dataset.remaining||'0',10)-1);
      expire.dataset.remaining=String(seconds);
      if(seconds<=0){expire.textContent='زمان نمایش این معرفی تمام شده است';return}
      const h=Math.floor(seconds/3600),m=Math.floor((seconds%3600)/60);
      expire.textContent=`${h} ساعت و ${m} دقیقه تا پایان نمایش`;
    },1000);
  }

  document.addEventListener('DOMContentLoaded',initStories);
})();
