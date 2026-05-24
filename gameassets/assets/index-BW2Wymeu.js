const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/ThumbnailRenderer-Bw9mWpJX.js","assets/babylon-core-BshMRevz.js","assets/babylon-loaders-BcrWWf8v.js","assets/GameManager-FgV9DF8M.js","assets/ItemIcon-BFPd60cf.js","assets/BakeApp-MTJ9RbXK.js"])))=>i.map(i=>d[i]);
import{al as C,o as wt}from"./babylon-core-BshMRevz.js";(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const r of document.querySelectorAll('link[rel="modulepreload"]'))a(r);new MutationObserver(r=>{for(const s of r)if(s.type==="childList")for(const o of s.addedNodes)o.tagName==="LINK"&&o.rel==="modulepreload"&&a(o)}).observe(document,{childList:!0,subtree:!0});function n(r){const s={};return r.integrity&&(s.integrity=r.integrity),r.referrerPolicy&&(s.referrerPolicy=r.referrerPolicy),r.crossOrigin==="use-credentials"?s.credentials="include":r.crossOrigin==="anonymous"?s.credentials="omit":s.credentials="same-origin",s}function a(r){if(r.ep)return;r.ep=!0;const s=n(r);fetch(r.href,s)}})();if(typeof console<"u"){const t=()=>{};console.debug=t,console.info=t,console.log=t,console.table=t,console.warn=t,console.error=t}const $="evilquest-preauth-theme";function at(){if(document.getElementById($))return;const t=document.createElement("style");t.id=$,t.textContent=`
    @keyframes eq-preauth-fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes eq-preauth-fade-out { from { opacity: 1; } to { opacity: 0; } }

    .eq-preauth-overlay {
      position: fixed;
      left: var(--eq-viewport-left, 0px);
      top: var(--eq-viewport-top, 0px);
      width: var(--eq-viewport-width, 100vw);
      height: var(--eq-viewport-height, 100vh);
      background: #050505;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-family: Arial, Helvetica, sans-serif;
    }

    .eq-preauth-overlay::before {
      content: "";
      position: absolute;
      inset: -50vmax;
      z-index: 0;
      background:
        linear-gradient(rgba(0, 0, 0, 0.72), rgba(0, 0, 0, 0.86)),
        url('/ui/stone-bg.png') repeat;
      transform: rotate(90deg);
      transform-origin: center;
      pointer-events: none;
    }

    .eq-preauth-overlay > * {
      position: relative;
      z-index: 1;
    }

    .eq-preauth-brand {
      font-family: 'Cinzel', 'Times New Roman', serif;
      font-size: clamp(34px, 14vw, 68px);
      font-weight: 900;
      letter-spacing: clamp(1px, 1vw, 7px);
      line-height: 1;
      max-width: calc(var(--eq-viewport-width, 100vw) - 24px);
      white-space: nowrap;
      text-align: center;
      color: #d8372b;
      text-shadow: 2px 2px 0 #160604, 0 0 10px rgba(200, 28, 18, 0.22);
      user-select: none;
    }

    .eq-preauth-subtitle,
    .eq-loading-heading,
    .eq-loading-status,
    .eq-login-label {
      text-shadow: 1px 1px 0 #000;
    }

    .eq-loading-overlay {
      z-index: 99999;
      animation: eq-preauth-fade-in 120ms linear;
    }

    .eq-loading-overlay.fading-out {
      animation: eq-preauth-fade-out 220ms linear forwards;
      pointer-events: none;
    }

    .eq-loading-brand {
      margin-bottom: 26px;
    }

    .eq-loading-heading {
      color: #d7d0c2;
      font-size: 13px;
      font-weight: bold;
      margin-bottom: 8px;
    }

    .eq-loading-progress-wrap {
      width: 304px;
      max-width: min(70vw, calc(var(--eq-viewport-width, 100vw) - 24px));
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .eq-loading-progress-track {
      position: relative;
      width: 100%;
      height: 20px;
      background: #090909;
      border: 2px solid #2a2a2a;
      outline: 1px solid #000;
      overflow: hidden;
      box-shadow: inset 0 0 0 1px #151515;
    }

    .eq-loading-progress-fill {
      height: 100%;
      width: 0%;
      background:
        repeating-linear-gradient(90deg, rgba(0,0,0,0.18) 0 2px, transparent 2px 8px),
        linear-gradient(180deg, #be3024 0%, #8c1510 54%, #540b08 100%);
      transition: width 90ms linear;
    }

    .eq-loading-progress-text {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #e8e0cf;
      font-size: 11px;
      line-height: 20px;
      font-weight: bold;
      text-shadow: 1px 1px 0 #000;
      pointer-events: none;
      font-variant-numeric: tabular-nums;
    }

    .eq-loading-status {
      margin-top: 8px;
      font-size: 12px;
      color: #a09a90;
      max-width: min(70vw, calc(var(--eq-viewport-width, 100vw) - 24px));
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .eq-login-overlay {
      z-index: 9999;
    }

    .eq-login-brand {
      margin-bottom: 10px;
    }

    .eq-preauth-subtitle {
      font-size: 12px;
      color: #8a857c;
      margin-bottom: 18px;
    }

    .eq-login-card {
      width: 304px;
      background: #090909;
      border: 2px solid #2a2a2a;
      outline: 1px solid #000;
      padding: 12px;
      box-shadow: inset 0 0 0 1px #151515;
    }

    .eq-login-vignette {
      position: absolute;
      left: calc(50% + 160px);
      top: 226px;
      width: 280px;
      height: 420px;
      z-index: 1;
      opacity: 0.86;
      pointer-events: none;
      filter: saturate(0.86) contrast(1.18) brightness(1.18)
        drop-shadow(0 24px 28px rgba(0, 0, 0, 0.78));
      mask-image: radial-gradient(ellipse at center, #000 42%, rgba(0,0,0,0.84) 62%, rgba(0,0,0,0) 84%);
    }

    .eq-login-vignette::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse at 50% 78%, rgba(144, 38, 28, 0.16), rgba(0,0,0,0) 46%),
        linear-gradient(90deg, rgba(0,0,0,0.88), rgba(0,0,0,0) 36%, rgba(0,0,0,0.42));
      pointer-events: none;
    }

    .eq-login-vignette-image {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: contain;
      image-rendering: auto;
    }

    .eq-login-tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4px;
      margin-bottom: 10px;
    }

    .eq-login-tab,
    .eq-login-submit {
      outline: 1px solid #000;
      text-shadow: 1px 1px 0 #000;
      font-weight: bold;
      cursor: pointer;
    }

    .eq-login-tab {
      text-align: center;
      padding: 7px 0;
      font-size: 12px;
      border: 2px solid #252525;
      color: #81796d;
      background: #080808;
      box-shadow: inset 0 0 0 1px #121212;
    }

    .eq-login-tab.is-active {
      border-color: #6b2a22;
      color: #f0e6d0;
      background: #3a100d;
      box-shadow: inset 0 0 0 1px #1c0907;
    }

    .eq-login-error {
      display: none;
      padding: 7px;
      margin-bottom: 10px;
      background: #160706;
      border: 1px solid #672019;
      color: #e8c2b8;
      font-size: 12px;
      text-align: center;
      text-shadow: 1px 1px 0 #000;
    }

    .eq-login-field {
      margin-bottom: 9px;
    }

    .eq-login-label {
      font-size: 11px;
      color: #b8b0a2;
      margin-bottom: 3px;
      font-weight: bold;
    }

    .eq-login-input {
      width: 100%;
      padding: 7px 8px;
      box-sizing: border-box;
      background: #020202;
      border: 2px solid #2a2a2a;
      outline: 1px solid #000;
      color: #e8e0cf;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 16px;
      box-shadow: inset 0 0 0 1px #101010;
    }

    .eq-login-input:focus {
      border-color: #6b2a22;
      box-shadow: inset 0 0 0 1px #1b0c0a;
    }

    .eq-login-remember {
      display: flex;
      align-items: center;
      gap: 7px;
      margin: 2px 0 9px;
      color: #a79f90;
      font-size: 11px;
      font-weight: bold;
      line-height: 1.2;
      cursor: pointer;
      user-select: none;
      text-shadow: 1px 1px 0 #000;
    }

    .eq-login-remember input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }

    .eq-login-checkbox-box {
      width: 14px;
      height: 14px;
      flex: 0 0 14px;
      background: #020202;
      border: 2px solid #2a2a2a;
      outline: 1px solid #000;
      box-shadow: inset 0 0 0 1px #101010;
    }

    .eq-login-remember input:checked + .eq-login-checkbox-box {
      background:
        linear-gradient(135deg, transparent 0 36%, #d7c7a8 36% 52%, transparent 52%),
        linear-gradient(45deg, transparent 0 44%, #d7c7a8 44% 60%, transparent 60%),
        #3a100d;
      border-color: #6b2a22;
      box-shadow: inset 0 0 0 1px #1b0c0a;
    }

    .eq-login-remember:hover {
      color: #d7d0c2;
    }

    .eq-login-signup-closed {
      padding: 12px 10px;
      margin-top: 2px;
      background: #080202;
      border: 1px solid #672019;
      box-shadow: inset 0 0 0 1px #1b0806;
      color: #d7d0c2;
      font-size: 12px;
      line-height: 1.45;
      text-align: center;
      text-shadow: 1px 1px 0 #000;
    }

    .eq-login-signup-closed p {
      margin: 0 0 8px;
    }

    .eq-login-signup-closed p:last-child {
      margin-bottom: 0;
    }

    .eq-login-signup-closed a {
      color: #c85a4d;
      font-weight: bold;
      text-decoration: none;
    }

    .eq-login-signup-closed a:hover {
      color: #e07163;
      text-decoration: underline;
    }

    .eq-login-submit {
      width: 100%;
      padding: 8px;
      margin-top: 8px;
      background: #120606;
      border: 2px solid #6b2a22;
      color: #e6d6bd;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 13px;
      box-shadow: inset 0 0 0 1px #1b0806;
    }

    .eq-login-submit:hover {
      background: #3a100d;
      border-color: #8c3026;
      color: #fff0d8;
      box-shadow: inset 0 0 0 1px #280b08;
    }

    .eq-login-submit:disabled {
      cursor: default;
      opacity: 0.72;
    }

    @media (max-width: 820px) {
      .eq-login-vignette {
        display: none;
      }
    }

  `,document.head.appendChild(t)}var q=(t=>(t[t.LOGIN=1]="LOGIN",t[t.CRYPTO_RESPONSE=2]="CRYPTO_RESPONSE",t[t.PLAYER_MOVE=10]="PLAYER_MOVE",t[t.PLAYER_ATTACK_NPC=20]="PLAYER_ATTACK_NPC",t[t.PLAYER_TALK_NPC=21]="PLAYER_TALK_NPC",t[t.PLAYER_FOLLOW=23]="PLAYER_FOLLOW",t[t.PLAYER_PICKUP_ITEM=30]="PLAYER_PICKUP_ITEM",t[t.PLAYER_DROP_ITEM=31]="PLAYER_DROP_ITEM",t[t.PLAYER_EQUIP_ITEM=32]="PLAYER_EQUIP_ITEM",t[t.PLAYER_UNEQUIP_ITEM=33]="PLAYER_UNEQUIP_ITEM",t[t.PLAYER_EAT_ITEM=34]="PLAYER_EAT_ITEM",t[t.PLAYER_SET_STANCE=35]="PLAYER_SET_STANCE",t[t.PLAYER_BUY_ITEM=36]="PLAYER_BUY_ITEM",t[t.PLAYER_SELL_ITEM=37]="PLAYER_SELL_ITEM",t[t.PLAYER_MOVE_INV_ITEM=38]="PLAYER_MOVE_INV_ITEM",t[t.DIALOGUE_CHOOSE=22]="DIALOGUE_CHOOSE",t[t.PLAYER_INTERACT_OBJECT=40]="PLAYER_INTERACT_OBJECT",t[t.PLAYER_USE_ITEM_ON_ITEM=41]="PLAYER_USE_ITEM_ON_ITEM",t[t.PLAYER_USE_ITEM_ON_OBJECT=42]="PLAYER_USE_ITEM_ON_OBJECT",t[t.PLAYER_USE_ITEM_ON_NPC=43]="PLAYER_USE_ITEM_ON_NPC",t[t.PLAYER_CAST_SPELL=44]="PLAYER_CAST_SPELL",t[t.PLAYER_SET_AUTOCAST=45]="PLAYER_SET_AUTOCAST",t[t.MAP_READY=50]="MAP_READY",t[t.SET_APPEARANCE=60]="SET_APPEARANCE",t[t.CLIENT_FLOOR_HINT=70]="CLIENT_FLOOR_HINT",t[t.CLIENT_POSITION_Y=71]="CLIENT_POSITION_Y",t[t.BANK_REQUEST_OPEN=80]="BANK_REQUEST_OPEN",t[t.BANK_DEPOSIT=81]="BANK_DEPOSIT",t[t.BANK_WITHDRAW=82]="BANK_WITHDRAW",t[t.BANK_CLOSE=83]="BANK_CLOSE",t[t.TRADE_REQUEST=90]="TRADE_REQUEST",t[t.TRADE_ACCEPT_REQUEST=91]="TRADE_ACCEPT_REQUEST",t[t.TRADE_DECLINE=92]="TRADE_DECLINE",t[t.TRADE_OFFER_ITEM=93]="TRADE_OFFER_ITEM",t[t.TRADE_REMOVE_OFFERED=94]="TRADE_REMOVE_OFFERED",t[t.TRADE_ACCEPT=95]="TRADE_ACCEPT",t[t.DUEL_REQUEST=100]="DUEL_REQUEST",t[t.DUEL_ACCEPT_REQUEST=101]="DUEL_ACCEPT_REQUEST",t[t.DUEL_DECLINE=102]="DUEL_DECLINE",t[t.DUEL_STAKE_ITEM=103]="DUEL_STAKE_ITEM",t[t.DUEL_REMOVE_STAKE=104]="DUEL_REMOVE_STAKE",t[t.DUEL_ACCEPT=105]="DUEL_ACCEPT",t[t.CLIENT_PING=120]="CLIENT_PING",t[t.CLIENT_ACTIVITY=121]="CLIENT_ACTIVITY",t[t.CURSOR_POSITION=122]="CURSOR_POSITION",t))(q||{}),Tt=(t=>(t[t.Legacy=0]="Legacy",t[t.Pointer=1]="Pointer",t[t.Keyboard=2]="Keyboard",t[t.Touch=3]="Touch",t))(Tt||{}),x=(t=>(t[t.LOGIN_OK=1]="LOGIN_OK",t[t.CRYPTO_CHALLENGE=2]="CRYPTO_CHALLENGE",t[t.OPCODE_MAPPING=3]="OPCODE_MAPPING",t[t.PLAYER_SYNC=10]="PLAYER_SYNC",t[t.NPC_SYNC=11]="NPC_SYNC",t[t.GROUND_ITEM_SYNC=12]="GROUND_ITEM_SYNC",t[t.PLAYER_STATS=21]="PLAYER_STATS",t[t.PLAYER_SKILLS=22]="PLAYER_SKILLS",t[t.PLAYER_EQUIPMENT=23]="PLAYER_EQUIPMENT",t[t.PLAYER_INVENTORY_BATCH=24]="PLAYER_INVENTORY_BATCH",t[t.PLAYER_SKILLS_BATCH=25]="PLAYER_SKILLS_BATCH",t[t.PLAYER_EQUIPMENT_BATCH=26]="PLAYER_EQUIPMENT_BATCH",t[t.COMBAT_HIT=30]="COMBAT_HIT",t[t.ENTITY_DEATH=31]="ENTITY_DEATH",t[t.XP_GAIN=32]="XP_GAIN",t[t.LEVEL_UP=33]="LEVEL_UP",t[t.COMBAT_PROJECTILE=34]="COMBAT_PROJECTILE",t[t.SPELL_CAST=35]="SPELL_CAST",t[t.CHAT_SYSTEM=42]="CHAT_SYSTEM",t[t.SHOP_OPEN=50]="SHOP_OPEN",t[t.WORLD_OBJECT_SYNC=55]="WORLD_OBJECT_SYNC",t[t.WORLD_OBJECT_DEPLETED=56]="WORLD_OBJECT_DEPLETED",t[t.SKILLING_START=57]="SKILLING_START",t[t.SKILLING_STOP=58]="SKILLING_STOP",t[t.SMITHING_OPEN=59]="SMITHING_OPEN",t[t.MAP_CHANGE=60]="MAP_CHANGE",t[t.FLOOR_CHANGE=61]="FLOOR_CHANGE",t[t.SHOW_CHARACTER_CREATOR=70]="SHOW_CHARACTER_CREATOR",t[t.PLAYER_TELEPORT=71]="PLAYER_TELEPORT",t[t.PLAYER_REMOTE_EQUIPMENT=72]="PLAYER_REMOTE_EQUIPMENT",t[t.NPC_APPEARANCE=73]="NPC_APPEARANCE",t[t.NPC_EQUIPMENT=74]="NPC_EQUIPMENT",t[t.PLAYER_REMOTE_STANCE=75]="PLAYER_REMOTE_STANCE",t[t.DIALOGUE_OPEN=76]="DIALOGUE_OPEN",t[t.DIALOGUE_CLOSE=77]="DIALOGUE_CLOSE",t[t.NPC_INTERACTIONS=78]="NPC_INTERACTIONS",t[t.PLAYER_ANIMATION=79]="PLAYER_ANIMATION",t[t.NPC_NAME=84]="NPC_NAME",t[t.NPC_FACING=85]="NPC_FACING",t[t.NPC_CUSTOM_COLORS=86]="NPC_CUSTOM_COLORS",t[t.NPC_ATTACK_ANIM=87]="NPC_ATTACK_ANIM",t[t.RENOWN_SYNC=88]="RENOWN_SYNC",t[t.BANK_OPEN=80]="BANK_OPEN",t[t.BANK_UPDATE_SLOT=81]="BANK_UPDATE_SLOT",t[t.BANK_CLOSE=82]="BANK_CLOSE",t[t.TRADE_REQUEST_RECEIVED=90]="TRADE_REQUEST_RECEIVED",t[t.TRADE_OPEN=91]="TRADE_OPEN",t[t.TRADE_OFFER_UPDATE=92]="TRADE_OFFER_UPDATE",t[t.TRADE_ACCEPT_STATE=93]="TRADE_ACCEPT_STATE",t[t.TRADE_CLOSE=94]="TRADE_CLOSE",t[t.TRADE_TEST_OPEN=95]="TRADE_TEST_OPEN",t[t.DUEL_REQUEST_RECEIVED=96]="DUEL_REQUEST_RECEIVED",t[t.DUEL_OPEN=97]="DUEL_OPEN",t[t.DUEL_STAKE_UPDATE=98]="DUEL_STAKE_UPDATE",t[t.DUEL_ACCEPT_STATE=99]="DUEL_ACCEPT_STATE",t[t.DUEL_CLOSE=101]="DUEL_CLOSE",t[t.DUEL_START=102]="DUEL_START",t[t.DUEL_FINISH=103]="DUEL_FINISH",t[t.PATH_TRUNCATED=100]="PATH_TRUNCATED",t[t.QUEST_STATE_SYNC=110]="QUEST_STATE_SYNC",t[t.QUEST_STAGE_ADVANCED=111]="QUEST_STAGE_ADVANCED",t[t.ADMIN_FLAGS=120]="ADMIN_FLAGS",t[t.SERVER_PONG=121]="SERVER_PONG",t[t.PLAYER_SELF_SYNC=122]="PLAYER_SELF_SYNC",t))(x||{}),bt=(t=>(t[t.Despawn=0]="Despawn",t[t.Death=1]="Death",t))(bt||{}),At=(t=>(t[t.Idle=0]="Idle",t[t.Skill=1]="Skill",t[t.Attack=2]="Attack",t))(At||{}),Pt=(t=>(t[t.None=0]="None",t[t.Chop=1]="Chop",t[t.Mine=2]="Mine",t[t.Magic=3]="Magic",t))(Pt||{});const xt=Math.PI/4,Lt=3*Math.PI/4,D=[{u:0,v:0},{u:1,v:0},{u:1,v:1},{u:0,v:1}],Rt=[D[1],D[2],D[3],D[0]];function me(t){return t==="back"?D:Rt}function It(t){let e=t%Math.PI;return e<0&&(e+=Math.PI),e}function fe(t){return t==="back"?xt:Lt}function pe(t,e,n,a){const r=(t-.5)/a+.5,s=(e-.5)/a+.5;return n===1?[-(s-.5)+.5,r-.5+.5]:n===2?[-(r-.5)+.5,-(s-.5)+.5]:n===3?[s-.5+.5,-(r-.5)+.5]:[r,s]}const yt=Object.freeze({u:0,v:0}),Nt=Object.freeze({u:1,v:0}),Ct=Object.freeze({u:1,v:1}),vt=Object.freeze({u:0,v:1}),Q=[yt,Nt,Ct,vt];function _e(t,e=0){const n=It(t),a=-Math.sin(n),r=Math.cos(n),s=Math.max(-.49,Math.min(.49,Number.isFinite(e)?e:0)),o=-.5*a+-.5*r+s,c=.5*a+-.5*r+s,i=.5*a+.5*r+s,l=-.5*a+.5*r+s,g=[o,c,i,l],d=1e-9,m=[],u=[],E=[];for(let _=0;_<4;_++){const T=Q[_],j=Q[(_+1)%4],b=g[_],H=g[(_+1)%4];if(b>=-d&&m.push(T),b<=d&&u.push(T),Math.abs(b)<=d&&E.length<2&&E.push(T),b>d&&H<-d||b<-d&&H>d){const z=b/(b-H),V={u:T.u+z*(j.u-T.u),v:T.v+z*(j.v-T.v)};m.push(V),u.push(V),E.length<2&&E.push(V)}}for(;E.length<2;)E.push({u:.5,v:.5});return{halfA:m,halfB:u,cutEndpoints:[E[0],E[1]]}}function we(t,e,n,a,r,s){const o=t*(1-r)+e*r,c=n*(1-r)+a*r;return o*(1-s)+c*s}var Mt=(t=>(t[t.GRASS=0]="GRASS",t[t.DIRT=1]="DIRT",t[t.STONE=2]="STONE",t[t.WATER=3]="WATER",t[t.WALL=4]="WALL",t[t.SAND=5]="SAND",t[t.WOOD=6]="WOOD",t[t.MUD=7]="MUD",t))(Mt||{});const Te=new Set([3,4]),be={N:1,E:2,S:4,W:8},Ae=1.8,Pe=["skinColor","shirtColor","pantsColor","shoesColor","beltColor","hairColor"],xe=1,St=["grass","dirt","sand","path","road","water","desert","sandstone","rock","drysand","dungeon-floor","dungeon-rock"],Le=Object.freeze(Object.fromEntries(St.map((t,e)=>[t,e]))),Re=255;function Dt(t){switch(t){case"grass":return 0;case"dirt":return 1;case"sand":return 5;case"path":return 1;case"road":return 2;case"water":return 7;case"desert":return 5;case"sandstone":return 2;case"rock":return 2;case"drysand":return 5;default:return 0}}function Ie(t,e,n){return Math.min(e.tl,e.tr,e.bl,e.br)<=n?3:t.waterPainted?7:Dt(t.ground)}function ye(t,e,n){return t.waterPainted?!0:Math.min(e.tl,e.tr,e.bl,e.br)<=n}const Ne=-1,Ut=64,qt=[{tier:1,itemIds:[224,225,226],goodMagicXp:10},{tier:2,itemIds:[227,228,229],goodMagicXp:35}];new Set(qt.flatMap(t=>t.itemIds));const rt=254,K=2,A=new TextEncoder;function p(){const t=globalThis.crypto?.subtle;if(!t)throw new Error("WebCrypto subtle API is unavailable");return t}function Ce(t){const e=new Uint8Array(t);return globalThis.crypto.getRandomValues(e),e}function kt(t){let e="";for(const n of t)e+=String.fromCharCode(n);return btoa(e).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"")}function O(t){const e=t.replace(/-/g,"+").replace(/_/g,"/"),n=e+"=".repeat((4-e.length%4)%4),a=atob(n),r=new Uint8Array(a.length);for(let s=0;s<a.length;s++)r[s]=a.charCodeAt(s);return r}function st(...t){const e=t.reduce((r,s)=>r+s.length,0),n=new Uint8Array(e);let a=0;for(const r of t)n.set(r,a),a+=r.length;return n}function f(t){const e=new Uint8Array(t.byteLength);return e.set(t),e.buffer}function k(t){if(t===null||typeof t!="object")return JSON.stringify(t);if(Array.isArray(t))return`[${t.map(k).join(",")}]`;const e=t;return`{${Object.keys(e).sort().map(n=>`${JSON.stringify(n)}:${k(e[n])}`).join(",")}}`}function ve(t){return A.encode(k({protocol:"evilquest-game-v2",protocolVersion:t.protocolVersion,accountId:t.accountId,deviceId:t.deviceId,connectionId:t.connectionId,serverNonce:t.serverNonce,clientNonce:t.clientNonce,serverPublicKey:t.serverPublicKey,clientPublicKey:t.clientPublicKey}))}async function v(...t){return new Uint8Array(await p().digest("SHA-256",f(st(...t))))}async function Me(){return p().generateKey({name:"ECDH",namedCurve:"P-256"},!0,["deriveBits"])}async function Se(t){return p().exportKey("jwk",t)}async function De(t){return p().importKey("jwk",t,{name:"ECDH",namedCurve:"P-256"},!1,[])}async function Ue(t,e){const n=await p().sign({name:"ECDSA",hash:"SHA-256"},t,f(e));return kt(new Uint8Array(n))}async function qe(t){const e=new Uint8Array(await p().deriveBits({name:"ECDH",public:t.peerPublicKey},t.privateKey,256)),n=await v(A.encode(t.authToken)),a=await v(t.transcript),r=O(t.serverNonce),s=O(t.clientNonce),o=await p().importKey("raw",f(st(e,n,a)),"HKDF",!1,["deriveKey","deriveBits"]),c=await v(A.encode("evilquest-game-v2:salt"),r,s,n),i=d=>p().deriveKey({name:"HKDF",hash:"SHA-256",salt:f(c),info:f(A.encode(`evilquest-game-v2:${d}:${t.connectionId}`))},o,{name:"AES-GCM",length:256},!1,["encrypt","decrypt"]),l=await v(A.encode("evilquest-game-v2:iv:client-to-server"),a),g=await v(A.encode("evilquest-game-v2:iv:server-to-client"),a);return{clientToServerKey:await i("client-to-server"),serverToClientKey:await i("server-to-client"),clientToServerIvPrefix:l.slice(0,4),serverToClientIvPrefix:g.slice(0,4),connectionId:t.connectionId,accountId:t.accountId}}function ot(t,e,n){const a=new Uint8Array(12);return a.set(e==="client-to-server"?t.clientToServerIvPrefix:t.serverToClientIvPrefix,0),new DataView(a.buffer).setBigUint64(4,BigInt(n)),a}function it(t,e,n){return A.encode(k({frame:"evilquest-game-v2",version:K,connectionId:t.connectionId,accountId:t.accountId,direction:e,counter:n}))}async function ke(t,e,n,a){const r=t.clientToServerKey,s=new Uint8Array(await p().encrypt({name:"AES-GCM",iv:f(ot(t,e,n)),additionalData:f(it(t,e,n))},r,f(a))),o=new Uint8Array(10+s.length);return o[0]=rt,o[1]=K,new DataView(o.buffer).setBigUint64(2,BigInt(n)),o.set(s,10),o}async function Ye(t,e,n){if(n.byteLength<11)throw new RangeError("encrypted v2 frame too short");const a=new DataView(n);if(a.getUint8(0)!==rt)throw new RangeError("not an encrypted v2 game frame");if(a.getUint8(1)!==K)throw new RangeError("unsupported game crypto version");const r=Number(a.getBigUint64(2));if(!Number.isSafeInteger(r))throw new RangeError("encrypted v2 counter too large");const s=t.serverToClientKey,o=new Uint8Array(n,10),c=await p().decrypt({name:"AES-GCM",iv:f(ot(t,e,r)),additionalData:f(it(t,e,r))},s,f(o));return{counter:r,plaintext:c}}const Yt=1,Gt=new Set([0,q.CRYPTO_RESPONSE,x.CRYPTO_CHALLENGE,x.OPCODE_MAPPING,254,255]),Bt=new Set([q.LOGIN,q.CRYPTO_RESPONSE]),Ht=new Set([x.CRYPTO_CHALLENGE,x.OPCODE_MAPPING]);function lt(t){return[...new Set(Object.values(t).filter(e=>typeof e=="number"))].sort((e,n)=>e-n)}const Vt=lt(q).filter(t=>!Bt.has(t)),ct=lt(x).filter(t=>!Ht.has(t)),ut=new Set([x.ADMIN_FLAGS]),Ft=ct.filter(t=>!ut.has(t)),Wt=ct.filter(t=>ut.has(t));function J(t){const e=new Map;for(const[n,a]of t){if(e.has(a))throw new Error(`duplicate wire opcode ${a}`);e.set(a,n)}return e}function X(t,e,n=[]){const a=new Map,r=new Set,s=(o,c)=>{const i=t[String(o)];if(i===void 0&&c)return;if(!Number.isInteger(i)||i<1||i>253)throw new Error(`missing opcode mapping for ${o}`);const l=i;if(Gt.has(l))throw new Error(`reserved wire opcode ${l}`);if(l===o)throw new Error(`unrotated opcode ${o}`);if(r.has(l))throw new Error(`duplicate wire opcode ${l}`);r.add(l),a.set(o,l)};for(const o of e)s(o,!1);for(const o of n)s(o,!0);return a}function Ge(t){if(!t||typeof t!="object")throw new Error("invalid opcode mapping payload");const e=t;if(e.version!==Yt)throw new Error("unsupported opcode mapping version");if(!e.client||typeof e.client!="object")throw new Error("missing client opcode mapping");if(!e.server||typeof e.server!="object")throw new Error("missing server opcode mapping");const n=X(e.client,Vt),a=X(e.server,Ft,Wt);return{clientLogicalToWire:n,clientWireToLogical:J(n),serverLogicalToWire:a,serverWireToLogical:J(a)}}function Kt(t,e,n=!1){if(t.byteLength===0)return t;const a=t[0],r=e.get(a);if(r===void 0){if(n)throw new Error(`unmapped opcode ${a}`);return t}const s=t.slice();return s[0]=r,s}function Be(t,e,n=!1){const a=new Uint8Array(t),r=Kt(a,e,n);if(r===a)return t;const s=new Uint8Array(r.byteLength);return s.set(r),s.buffer}const dt="6LernPcsAAAAAFOmpY461CSMDS9oYV42t6Cj4ExQ",Z="eq-recaptcha-v3";let M=null;function ht(){return M||(M=new Promise((t,e)=>{if(document.getElementById(Z)){t();return}const n=document.createElement("script");n.id=Z,n.src=`https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(dt)}`,n.async=!0,n.defer=!0,n.onload=()=>t(),n.onerror=()=>{M=null,e(new Error("Failed to load reCAPTCHA script"))},document.head.appendChild(n)}),M)}function jt(){ht().catch(()=>{})}async function zt(t){try{await ht();const e=window.grecaptcha;return e?(await new Promise(n=>e.ready(n)),await e.execute(dt,{action:t})):null}catch{return null}}class $t{container;onLogin;activeMode="login";errorEl=null;submitBtn=null;rememberUsernameRow=null;rememberUsernameInput=null;vignetteIdleCallback=null;vignetteTimeout=null;constructor(e){this.onLogin=e,this.container=this.buildUI(),document.body.appendChild(this.container),jt()}buildUI(){at();const e=document.createElement("div");e.id="login-screen",e.className="eq-preauth-overlay eq-login-overlay";const n=document.createElement("div");n.textContent="EvilQuest",n.className="eq-preauth-brand eq-login-brand",e.appendChild(n);const a=document.createElement("div");a.textContent="A Browser MMORPG Adventure",a.className="eq-preauth-subtitle",e.appendChild(a);const r=this.createVignette();e.appendChild(r);const s=document.createElement("div");s.className="eq-login-card";const o=document.createElement("div");o.className="eq-login-tabs";const c=this.createTab("Login","login"),i=this.createTab("Sign Up","signup");o.appendChild(c),o.appendChild(i),s.appendChild(o),this.errorEl=document.createElement("div"),this.errorEl.className="eq-login-error",s.appendChild(this.errorEl);const l=document.createElement("div");l.id="login-form";const g=this.createInput("Username","text","login-username"),d=this.createInput("Password","password","login-password"),m=this.createInput("Confirm Password","password","login-confirm");m.style.display="none",m.dataset.signupOnly="true",l.appendChild(g),l.appendChild(d),l.appendChild(m),l.appendChild(this.createRememberUsernameRow());const u=document.createElement("button");return u.id="login-submit",u.className="eq-login-submit",u.textContent="Login",u.addEventListener("click",()=>this.handleSubmit()),this.submitBtn=u,l.appendChild(u),l.appendChild(this.createRecaptchaNotice()),s.appendChild(l),e.appendChild(s),e.addEventListener("keydown",E=>{E.key==="Enter"&&this.handleSubmit()}),setTimeout(()=>{const E=this.container.querySelector("#login-username"),_=this.getSavedUsername();if(E&&_){E.value=_,this.container.querySelector("#login-password")?.focus();return}E?.focus()},100),e}createVignette(){const e=document.createElement("div");e.className="eq-login-vignette",e.setAttribute("aria-hidden","true");const n=document.createElement("img");return n.className="eq-login-vignette-image",n.alt="",n.draggable=!1,e.appendChild(n),this.deferVignetteLoad(n),e}deferVignetteLoad(e){const n=()=>{this.vignetteIdleCallback=null,this.vignetteTimeout=null,this.container.isConnected&&this.loadVignetteImage(e)};if("requestIdleCallback"in window){this.vignetteIdleCallback=window.requestIdleCallback(n,{timeout:2500});return}this.vignetteTimeout=setTimeout(n,1500)}async loadVignetteImage(e){try{const{getThumbnail:n}=await C(async()=>{const{getThumbnail:r}=await import("./ThumbnailRenderer-Bw9mWpJX.js").then(s=>s.T);return{getThumbnail:r}},__vite__mapDeps([0,1,2])),a=await n("/assets/bought-assets/Medieval_Dracula/Gargoyle_Var_1.gltf",{camera:{alpha:-Math.PI/4,beta:Math.PI/2.7,distanceMult:.7},rotationY:Math.PI*.12});a&&this.container.isConnected&&(e.src=a)}catch{}}createTab(e,n){const a=document.createElement("div");return a.textContent=e,a.dataset.mode=n,a.className=`eq-login-tab${n===this.activeMode?" is-active":""}`,a.addEventListener("click",()=>this.switchMode(n)),a}createInput(e,n,a){const r=document.createElement("div");r.className="eq-login-field";const s=document.createElement("div");s.textContent=e,s.className="eq-login-label",r.appendChild(s);const o=document.createElement("input");return o.id=a,o.type=n,o.maxLength=n==="password"?Ut:16,o.className="eq-login-input",r.appendChild(o),r}createRememberUsernameRow(){const e=document.createElement("label");e.className="eq-login-remember",this.rememberUsernameRow=e;const n=document.createElement("input");n.type="checkbox",n.checked=!!this.getSavedUsername(),this.rememberUsernameInput=n;const a=document.createElement("span");a.className="eq-login-checkbox-box";const r=document.createElement("span");return r.textContent="Remember username on this device",e.appendChild(n),e.appendChild(a),e.appendChild(r),e}createRecaptchaNotice(){const e=document.createElement("div");return e.className="eq-login-recaptcha-notice",e.style.cssText="margin-top:8px;font-size:10px;line-height:1.4;color:#9a8c70;text-align:center;",e.innerHTML='This site is protected by reCAPTCHA and the Google <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" style="color:#c9b78a;">Privacy Policy</a> and <a href="https://policies.google.com/terms" target="_blank" rel="noopener noreferrer" style="color:#c9b78a;">Terms of Service</a> apply.',e}getSavedUsername(){return localStorage.getItem("evilquest_saved_username")||""}syncRememberedUsername(e){if(this.rememberUsernameInput?.checked){localStorage.setItem("evilquest_saved_username",e);return}localStorage.removeItem("evilquest_saved_username")}switchMode(e){this.activeMode=e,this.hideError(),this.container.querySelectorAll("[data-mode]").forEach(o=>{const c=o;c.classList.toggle("is-active",c.dataset.mode===e)}),this.container.querySelectorAll(".eq-login-field").forEach(o=>{o.style.display=""});const r=this.container.querySelector("[data-signup-only]");r&&(r.style.display=e==="signup"?"":"none");const s=this.submitBtn;s&&(s.textContent=e==="login"?"Login":"Sign Up",s.style.display=""),this.rememberUsernameRow&&(this.rememberUsernameRow.style.display=e==="login"?"flex":"none")}async handleSubmit(){const e=this.container.querySelector("#login-username")?.value.trim(),n=this.container.querySelector("#login-password")?.value,a=this.container.querySelector("#login-confirm")?.value;if(!e||!n){this.showError("Please fill in all fields");return}if(this.activeMode==="signup"&&n!==a){this.showError("Passwords do not match");return}const r=this.submitBtn;r&&(r.textContent="Please wait...",r.disabled=!0);try{const s=await(await C(async()=>{const{getDeviceId:l}=await import("./deviceId-BRNXmaxb.js");return{getDeviceId:l}},[])).getDeviceId(),o=await zt(this.activeMode),i=await(await fetch(`/api/${this.activeMode}`,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({username:e,password:n,deviceId:s,recaptchaToken:o})})).json();i.ok?(this.syncRememberedUsername(i.username||e),localStorage.setItem("projectrs_token",i.token),localStorage.setItem("projectrs_username",i.username||e),r&&(r.textContent="Entering world..."),await this.onLogin(i.token,i.username||e)):this.showError(i.error||"Unknown error")}catch(s){this.showError(this.formatSubmitError(s))}finally{r&&this.container.isConnected&&(r.textContent=this.activeMode==="login"?"Login":"Sign Up",r.disabled=!1)}}formatSubmitError(e){const n=e instanceof Error?e.message:String(e??""),a="USER_VISIBLE:";return n.startsWith(a)?n.slice(a.length):/webgl|webgl2|graphics|gpu|failed to create engine|failed to create webgl context|exhausted gl driver|tryangle/i.test(n)?"EvilQuest could not start WebGL on this device. Enable hardware acceleration, update your graphics drivers, then reload.":"Connection failed — is the server running?"}showError(e){this.errorEl&&(this.errorEl.textContent=e,this.errorEl.style.display="block")}hideError(){this.errorEl&&(this.errorEl.style.display="none")}destroy(){this.vignetteIdleCallback!==null&&"cancelIdleCallback"in window&&(window.cancelIdleCallback(this.vignetteIdleCallback),this.vignetteIdleCallback=null),this.vignetteTimeout!==null&&(clearTimeout(this.vignetteTimeout),this.vignetteTimeout=null),this.container.remove()}}class B{overlay;statusEl;progressTrack;progressFill;progressTextEl;hidden=!1;currentPct=0;shownAtMs=0;static MIN_DISPLAY_MS=1500;constructor(){at(),this.overlay=document.createElement("div"),this.overlay.className="eq-preauth-overlay eq-loading-overlay";const e=document.createElement("div");e.className="eq-preauth-brand eq-loading-brand",e.textContent="EvilQuest",this.overlay.appendChild(e);const n=document.createElement("div");n.className="eq-loading-heading",n.textContent="Loading - please wait.",this.overlay.appendChild(n);const a=document.createElement("div");a.className="eq-loading-progress-wrap",this.progressTrack=document.createElement("div"),this.progressTrack.className="eq-loading-progress-track",this.progressFill=document.createElement("div"),this.progressFill.className="eq-loading-progress-fill",this.progressTrack.appendChild(this.progressFill),this.progressTextEl=document.createElement("div"),this.progressTextEl.className="eq-loading-progress-text",this.progressTextEl.textContent="0%",this.progressTrack.appendChild(this.progressTextEl),a.appendChild(this.progressTrack),this.overlay.appendChild(a),this.statusEl=document.createElement("div"),this.statusEl.className="eq-loading-status",this.statusEl.textContent="Loading…",this.overlay.appendChild(this.statusEl)}show(){this.overlay.isConnected||(document.body.appendChild(this.overlay),this.shownAtMs=performance.now())}setStatus(e){this.statusEl.textContent=e}setProgress(e){const n=Math.max(0,Math.min(1,e));if(n<this.currentPct)return;this.currentPct=n;const a=Math.round(n*100);this.progressFill.style.width=`${a}%`,this.progressTextEl.textContent=`${a}%`}resetProgress(){this.currentPct=0,this.progressFill.style.width="0%",this.progressTextEl.textContent=""}hide(){if(this.hidden)return;const e=performance.now()-this.shownAtMs,n=Math.max(0,B.MIN_DISPLAY_MS-e);n>0?setTimeout(()=>this._hideNow(),n):this._hideNow()}_hideNow(){this.hidden||(this.hidden=!0,this.overlay.classList.add("fading-out"),setTimeout(()=>{this.overlay.remove()},240))}}const tt=[[0,0,0],[12,3,3],[24,5,4],[38,7,4],[55,10,5],[76,16,6],[98,25,8],[122,38,10],[146,54,13],[168,73,18],[190,94,26],[208,118,38],[222,144,56],[232,170,82],[238,190,112],[242,205,142]];class Qt{canvas;ctx=null;bufferCanvas;bufferCtx=null;imageData=null;heat=new Uint8Array(0);raf=0;lastMs=0;accumulator=0;resizeHandler=null;visibilityHandler=null;hidden=!1;logicalW=0;logicalH=0;fireTopPx=0;constructor(){this.canvas=document.createElement("canvas"),this.canvas.id="background-particles",this.canvas.style.cssText=`
      position: fixed; inset: 0;
      z-index: 100000; pointer-events: none;
      background: transparent;
      image-rendering: pixelated;
    `,this.bufferCanvas=document.createElement("canvas"),document.body.appendChild(this.canvas),this.start()}pause(){this.raf&&(cancelAnimationFrame(this.raf),this.raf=0)}resume(){this.raf||(this.lastMs=performance.now(),this.loop())}setVisible(e){this.canvas.style.display=e?"":"none",this.hidden=!e,e?this.resume():this.pause()}destroy(){this.pause(),this.resizeHandler&&window.removeEventListener("resize",this.resizeHandler),this.visibilityHandler&&document.removeEventListener("visibilitychange",this.visibilityHandler),this.canvas.remove()}start(){const e=this.canvas.getContext("2d"),n=this.bufferCanvas.getContext("2d",{alpha:!0});if(!e||!n)return;this.ctx=e,this.bufferCtx=n,e.imageSmoothingEnabled=!1,n.imageSmoothingEnabled=!1;const a=()=>this.resize();a(),this.resizeHandler=a,window.addEventListener("resize",a);const r=()=>{document.visibilityState==="hidden"?this.pause():this.hidden||this.resume()};this.visibilityHandler=r,document.addEventListener("visibilitychange",r),this.lastMs=performance.now(),this.loop()}resize(){const e=this.ctx;if(!e||!this.bufferCtx)return;const n=window.devicePixelRatio||1,a=window.innerWidth,r=window.innerHeight;this.canvas.width=Math.round(a*n),this.canvas.height=Math.round(r*n),this.canvas.style.width=`${a}px`,this.canvas.style.height=`${r}px`,e.setTransform(n,0,0,n,0,0),e.imageSmoothingEnabled=!1;const s=Math.max(5,Math.min(8,Math.floor(a/180)));this.logicalW=Math.max(120,Math.ceil(a/s)),this.logicalH=Math.max(18,Math.ceil(r*.15/s)),this.fireTopPx=Math.max(0,r-this.logicalH*s),this.bufferCanvas.width=this.logicalW,this.bufferCanvas.height=this.logicalH,this.imageData=this.bufferCtx.createImageData(this.logicalW,this.logicalH),this.heat=new Uint8Array(this.logicalW*this.logicalH),this.seedBaseRows()}loop(){const e=n=>{const a=Math.min(80,n-this.lastMs)/1e3;this.lastMs=n,this.accumulator+=a;const r=1/11;for(;this.accumulator>=r;)this.step(),this.accumulator-=r;this.draw(),this.raf=requestAnimationFrame(e)};this.raf=requestAnimationFrame(e)}seedBaseRows(){const e=this.logicalW,n=this.logicalH;if(!(!e||!n))for(let a=n-4;a<n;a++)for(let r=0;r<e;r++)this.heat[a*e+r]=Math.random()>.18?15:10}step(){const e=this.logicalW,n=this.logicalH;if(!(!e||!n)){for(let a=0;a<e;a++){const r=Math.floor(a/8)%4,s=Math.random()>(r===0?.66:.52);this.heat[(n-1)*e+a]=s?14:4+Math.floor(Math.random()*5),this.heat[(n-2)*e+a]=s?11:4}for(let a=0;a<n-2;a++)for(let r=0;r<e;r++){const s=a+1,o=Math.floor(Math.random()*3)-1,c=Math.max(0,Math.min(e-1,r+o)),i=s*e+c,l=Math.random()>.12?1:0,g=Math.max(0,this.heat[i]-l);this.heat[a*e+r]=g}for(let a=0;a<Math.max(1,e/110);a++){if(Math.random()>.12)continue;const r=Math.floor(Math.random()*e),s=Math.floor(Math.random()*Math.max(6,n*.38));this.heat[s*e+r]=7+Math.floor(Math.random()*3)}}}draw(){const e=this.ctx,n=this.bufferCtx,a=this.imageData;if(!e||!n||!a)return;const r=a.data;for(let i=0;i<this.heat.length;i++){const l=this.heat[i],[g,d,m]=tt[l]??tt[0],u=i*4;r[u]=g,r[u+1]=d,r[u+2]=m,r[u+3]=l<=2?0:Math.min(145,20+l*8)}n.putImageData(a,0,0);const s=window.innerWidth,o=window.innerHeight;e.clearRect(0,0,s,o),e.imageSmoothingEnabled=!1;const c=o-this.fireTopPx;e.drawImage(this.bufferCanvas,0,this.fireTopPx,s,c),e.globalAlpha=.16,e.fillStyle="#050506";for(let i=o-24;i<o;i+=4)e.fillRect(0,i,s,2);e.globalAlpha=1}}const et="evilquest-global-scrollbars";function Ot(){if(document.getElementById(et))return;const t=document.createElement("style");t.id=et,t.textContent=`
    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"]) {
      scrollbar-width: thin;
      scrollbar-color: #71372d #15110d;
    }

    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"])::-webkit-scrollbar {
      width: 12px;
      height: 12px;
    }

    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"])::-webkit-scrollbar-track {
      background:
        repeating-linear-gradient(0deg, rgba(255,255,255,0.025) 0 1px, transparent 1px 4px),
        linear-gradient(90deg, #0f0c09 0%, #18130f 45%, #0b0907 100%);
      border-left: 1px solid #2d241b;
      border-top: 1px solid #2d241b;
      box-shadow: inset 1px 1px 0 rgba(0,0,0,0.65), inset -1px -1px 0 rgba(255,255,255,0.035);
    }

    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"])::-webkit-scrollbar-thumb {
      min-height: 24px;
      background:
        repeating-linear-gradient(0deg, rgba(255,210,150,0.08) 0 1px, transparent 1px 4px),
        linear-gradient(90deg, #52281f 0%, #7a3a2f 45%, #3b1c16 100%);
      border: 1px solid #110b08;
      box-shadow:
        inset 1px 1px 0 rgba(255,200,130,0.14),
        inset -1px -1px 0 rgba(0,0,0,0.55);
    }

    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"])::-webkit-scrollbar-thumb:hover {
      background:
        repeating-linear-gradient(0deg, rgba(255,220,160,0.1) 0 1px, transparent 1px 4px),
        linear-gradient(90deg, #633026 0%, #8a4638 45%, #442018 100%);
    }

    :where(#game-frame, #game-frame *, .eq-context-menu, [role="dialog"])::-webkit-scrollbar-corner {
      background: #0f0c09;
      border: 1px solid #2d241b;
    }
  `,document.head.appendChild(t)}const Jt="kcmap",Xt="projectrs_token",Zt=["/data/objects.json","/data/items.json","/data/npcs.json","/data/gear-overrides.json"],te=t=>[`/maps/${t}/meta.json`,`/maps/${t}/map.json?chunked=1`,`/maps/${t}/walls.json`,`/maps/${t}/biomes.json`];async function ee(t){const e=localStorage.getItem(Xt)||"",n=[...te(Jt),...Zt];let a=0;const r=n.length,s=o=>{t?.({loaded:a,total:r,pct:r>0?a/r:1,status:o??`Checking game cache (${a}/${r})`})};if(s("Checking game cache"),!e){a=r,s("Cache ready");return}await Promise.all(n.map(async o=>{try{const c=await fetch(o,{headers:{Authorization:`Bearer ${e}`},credentials:"same-origin"});c.ok&&await c.arrayBuffer()}catch{}a++,s()})),s("Cache ready")}class ne{startTime=performance.now();entries=[];mark(e,n){const a=performance.now()-this.startTime;this.entries.push({name:e,timeMs:a,detail:n}),performance.mark(`eq:${e}`)}measure(e,n,a){try{return performance.measure(`eq:${e}`,`eq:${n}`,a?`eq:${a}`:void 0)}catch{return null}}snapshot(){return[...this.entries]}table(){}}const h=new ne,nt="__projectrsSafeDynamicTextureUpdate";function ae(){const t=wt.prototype;if(t[nt])return;const e=t.update;t.update=function(...a){try{return this.getInternalTexture()?e.apply(this,a):void 0}catch(r){if(r instanceof TypeError&&String(r.message).includes("updateDynamicTexture"))return;throw r}},t[nt]=!0}const Et="USER_VISIBLE:",U="EvilQuest could not start WebGL on this device. Enable hardware acceleration, update your graphics drivers, then reload.",Y=document.getElementById("game-canvas"),w=document.getElementById("game-frame");Ot();ae();h.mark("entry");function gt(){const t=window.visualViewport?.scale??1;return Number.isFinite(t)&&t>0?t:1}function re(){const t=document.documentElement;let e=!1;const n=()=>{e=!1;const r=window.visualViewport,s=window.innerWidth||t.clientWidth||0,o=window.innerHeight||t.clientHeight||0,c=r?.width??s,i=r?.height??o,l=r?.offsetLeft??0,g=r?.offsetTop??0,d=Math.max(0,s-l-c),m=Math.max(0,o-g-i),u=gt();t.style.setProperty("--eq-viewport-width",`${Math.round(c)}px`),t.style.setProperty("--eq-viewport-height",`${Math.round(i)}px`),t.style.setProperty("--eq-viewport-left",`${Math.round(l)}px`),t.style.setProperty("--eq-viewport-top",`${Math.round(g)}px`),t.style.setProperty("--eq-viewport-right",`${Math.round(d)}px`),t.style.setProperty("--eq-viewport-bottom",`${Math.round(m)}px`),t.style.setProperty("--eq-viewport-scale",`${u.toFixed(3)}`),t.classList.toggle("eq-browser-page-zoomed",u>1.01),window.dispatchEvent(new Event("evilquest:viewportchange"))},a=()=>{e||(e=!0,window.requestAnimationFrame(n))};n(),window.addEventListener("resize",a,{passive:!0}),window.addEventListener("orientationchange",a,{passive:!0}),window.visualViewport?.addEventListener("resize",a,{passive:!0}),window.visualViewport?.addEventListener("scroll",a,{passive:!0})}function se(){const t=a=>(typeof a.composedPath=="function"?a.composedPath():[]).some(s=>s instanceof Element&&!!s.closest("#game-frame, .eq-preauth-overlay"))||document.querySelector(".eq-preauth-overlay")?!0:getComputedStyle(w).display!=="none",e=()=>gt()>1.01,n=a=>{t(a)&&(e()||a.preventDefault())};document.addEventListener("gesturestart",n,{passive:!1}),document.addEventListener("gesturechange",n,{passive:!1}),document.addEventListener("gestureend",n,{passive:!1}),document.addEventListener("dblclick",n,{passive:!1,capture:!0})}re();se();let y=null,S=null,N=null,R=null;const G=new Set;let P={pct:0,status:"Preparing game"};document.addEventListener("dragstart",t=>{if(!(t.target instanceof HTMLElement))return;const e=t.target;e.closest('input, textarea, [contenteditable="true"]')||(e instanceof HTMLImageElement||e.closest("img"))&&t.preventDefault()},!0);let F=null;function oe(){return F||(F=C(()=>import("./GameManager-FgV9DF8M.js"),__vite__mapDeps([3,1,2,0,4]))),F}function I(t){return new Error(`${Et}${t}`)}function ie(t){return t instanceof Error&&t.message.startsWith(Et)}function le(t){t?.getExtension("WEBGL_lose_context")?.loseContext()}function mt(t){const e=t instanceof Error?`${t.name} ${t.message}`:String(t);return/webgl|webgl2|graphics|gpu|failed to create engine|failed to create webgl context|exhausted gl driver|tryangle/i.test(e)}async function ce(){if(typeof window.WebGLRenderingContext>"u")throw I("Your browser or device does not appear to support WebGL. Enable hardware acceleration or try a current browser to play EvilQuest.");const t=document.createElement("canvas");let e=null;try{e=t.getContext("webgl2",{failIfMajorPerformanceCaveat:!1})??t.getContext("webgl",{failIfMajorPerformanceCaveat:!1})??t.getContext("experimental-webgl",{failIfMajorPerformanceCaveat:!1})}catch{throw I(U)}finally{le(e)}if(!e)throw I(U);try{const{Engine:n}=await C(async()=>{const{Engine:a}=await import("./babylon-core-BshMRevz.js").then(r=>r.ap);return{Engine:a}},[]);if(!n.isSupported())throw I(U)}catch(n){if(ie(n))throw n;if(mt(n))throw I(U)}}function L(t,e){const n=Math.max(0,Math.min(1,t));P={pct:Math.max(P.pct,n),status:e};for(const a of G)a(P)}function ft(t){return G.add(t),t(P),()=>G.delete(t)}function pt(){return R||(R=(async()=>{h.mark("game_prepare_start"),L(0,"Loading game code"),ee(e=>{L(e.pct*.15,e.status)}).catch(e=>{});{const{Logger:e}=await C(async()=>{const{Logger:n}=await import("./babylon-core-BshMRevz.js").then(a=>a.ar);return{Logger:n}},[]);e.LogLevels=e.ErrorLogLevel}L(.16,"Checking graphics support"),await ce();const{GameManager:t}=await oe();h.mark("game_module_loaded"),L(.18,"Preparing game engine"),w.style.display="grid",w.style.visibility="hidden",Y.offsetWidth;try{y=new t(Y,"","",ue)}catch(e){throw mt(e)?I(U):e}return h.mark("game_manager_created"),await y.whenPreloaded((e,n)=>{L(.18+e*.82,n)}),h.mark("game_preloaded"),h.measure("game_prepare_total","game_prepare_start","game_preloaded"),L(1,"Game ready"),y})().catch(t=>{R=null,P={pct:0,status:"Failed to prepare game"};for(const e of G)e(P);throw t}),R)}function ue(){y&&(y.destroy(),y=null),R=null,P={pct:0,status:"Preparing game"},localStorage.removeItem("projectrs_token"),localStorage.removeItem("projectrs_username"),W()}function _t(t=0){setTimeout(()=>{w.style.display="grid",w.style.visibility="visible",Y.offsetWidth,window.dispatchEvent(new Event("resize")),N?.setVisible(!1)},t)}function W(){h.mark("login_screen_show"),w.style.visibility="hidden",w.style.display="none",N?.setVisible(!1),S?.destroy(),S=new $t(async(t,e)=>{h.mark("manual_login_ok"),N?.setVisible(!1);const n=new B;n.show();const a=ft(r=>{n.setProgress(r.pct),n.setStatus(r.status)});try{const r=await pt();a(),n.resetProgress(),n.setStatus("Connecting to server"),w.style.display="grid",w.style.visibility="hidden",Y.offsetWidth,window.dispatchEvent(new Event("resize")),await r.connectAndAuth(t,e,(s,o)=>{n.setProgress(s),n.setStatus(o)}),h.mark("manual_game_connected"),S&&(S.destroy(),S=null),n.hide(),_t(340)}catch(r){throw a(),n.hide(),N?.setVisible(!1),r}})}async function de(){h.mark("token_validate_start");const t=localStorage.getItem("projectrs_token"),e=localStorage.getItem("projectrs_username");if(!t||!e)return h.mark("token_missing"),null;try{if((await(await fetch("/api/validate",{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({token:t})})).json()).ok)return h.mark("token_valid"),{token:t,username:e}}catch{}return localStorage.removeItem("projectrs_token"),localStorage.removeItem("projectrs_username"),h.mark("token_invalid"),null}async function he(){h.mark("bootstrap_start"),N=new Qt,N.setVisible(!1);const t=new B;t.show();const e=await de();if(!e){t.hide(),setTimeout(()=>W(),260);return}const n=ft(r=>{t.setProgress(r.pct),t.setStatus(r.status)}),a=pt();a.catch(r=>{});try{const r=await a;n(),t.resetProgress(),t.setStatus("Connecting to server"),await r.connectAndAuth(e.token,e.username,(s,o)=>{t.setProgress(s),t.setStatus(o)}),h.mark("auto_game_connected"),t.hide(),_t(340)}catch{n(),t.hide(),W()}}new URLSearchParams(window.location.search).get("bake")==="1"?C(async()=>{const{runBake:t}=await import("./BakeApp-MTJ9RbXK.js");return{runBake:t}},__vite__mapDeps([5,0,1,2,4])).then(({runBake:t})=>t()).catch(t=>{}):he().catch(t=>{const e=document.querySelector(".eq-loading-status");e&&(e.textContent="Failed to load. Please reload the page.")});export{Ue as A,xe as B,Pe as C,Ae as D,rt as E,pe as F,K as G,At as P,Ne as Q,x as S,Mt as T,be as W,Te as a,Tt as b,q as c,bt as d,St as e,Le as f,Re as g,Pt as h,we as i,ve as j,kt as k,Ie as l,_e as m,Ye as n,qe as o,ke as p,Se as q,me as r,Me as s,De as t,fe as u,Ge as v,Ce as w,Be as x,Kt as y,ye as z};
