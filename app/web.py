"""
The BRO Risk Oracle web UI.

Server-rendered, single-file styled interface over the existing API. Carries the
established BRO brand (forest green / navy / gold). It calls the same JSON API
the rest of the app exposes, via fetch, holding the JWT in memory (sessionStorage)
so the security model is identical to API clients — no separate auth path.

Mounted onto the FastAPI app at "/". The SPA-style shell talks to /api/v1/*.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import hashlib as _hashlib
import os as _os
_APP_JS_PATH = _os.path.join(_os.path.dirname(__file__), "static", "app.js")
try:
    _APP_JS_VER = _hashlib.md5(open(_APP_JS_PATH, "rb").read()).hexdigest()[:10]
except Exception:
    _APP_JS_VER = "1"

ui = APIRouter()

_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brata</title>
<meta name="theme-color" content="#0E1512">
<script>
/* Set the theme before first paint: a flash of the wrong appearance is the most
   common and most jarring defect in a themed application. */
(function(){try{
  var t=localStorage.getItem("brata_theme");
  if(!t) t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
  document.documentElement.setAttribute("data-theme",t);
}catch(e){document.documentElement.setAttribute("data-theme","light");}})();
</script>
<style>
  /* ============================================================================
     BRATA DESIGN SYSTEM v2 — "Slate & Ember"
     Self-hosted variable fonts (no external CDN: required for regulated deployment
     and removes a third-party request from every page load).
       Display  Bricolage Grotesque — optical, slightly irregular; carries character
                                      without the dated feel of a book serif.
       UI       Manrope             — semi-geometric humanist, true tabular figures,
                                      legible at 12px in dense risk tables.
       Data     Martian Mono        — wide, engineered; used only for identifiers,
                                      metric labels and code, never for prose.
     Every colour is a semantic token. Light and dark are peers, not a filter over
     one another — dark is a separate, hand-tuned surface ramp.
     ============================================================================ */
  @font-face{font-family:'Bricolage';font-style:normal;font-display:swap;font-weight:200 800;
    src:url('/static/fonts/bricolage-grotesque-latin-wght-normal.woff2') format('woff2-variations')}
  @font-face{font-family:'Manrope';font-style:normal;font-display:swap;font-weight:200 800;
    src:url('/static/fonts/manrope-latin-wght-normal.woff2') format('woff2-variations')}
  @font-face{font-family:'MartianMono';font-style:normal;font-display:swap;font-weight:300 700;
    src:url('/static/fonts/martian-mono-latin-wght-normal.woff2') format('woff2-variations')}

  :root{
    /* ---- brand hues (identical in both themes; only surfaces invert) ---- */
    --h-brand: 162;          /* deep evergreen  */
    --h-ember: 24;           /* ember / signal  */

    /* ---- LIGHT THEME (default) ---- */
    --paper:#FFFFFF;
    --soft:#F6F7F5;
    --softer:#EFF1EE;
    --sunken:#E8EBE7;
    --ink:#0E1512;            /* primary text  */
    --ink-2:#3A443E;          /* secondary     */
    --mute:#5F6B64;           /* tertiary — darkened: 4.34:1 on tinted rows, under AA */
    --faint:#7C8B84;   /* was #93A09A — measured 4.34:1 at 12.5px, under AA */          /* quaternary    */
    --line:#E2E7E2;
    --line-2:#EDF0EC;
    --line-strong:#CFD7D1;

    --accent:#145741;
    --accent-soft:#E7F0EB;
    --accent-ink:#FFFFFF;
    --accent-hover:#0F6B4E;

    --ember:#A8410F;   /* was #C2521B — 4.07:1 on paper at 12px, under AA */
    --ember-soft:#FBEDE4;

    --crit:#A32B24;   --crit-soft:#FBE9E7;
    --warn:#A66A0B;   --warn-soft:#FBF1DF;
    --ok:#1E6B45;     --ok-soft:#E5F2EA;
    --info:#1F4E6B;   --info-soft:#E4EEF4;

    --band-high:#A32B24; --band-elev:#A66A0B; --band-mod:#8A7413; --band-low:#1E6B45;

    /* ---- typography scale (major third at the top, tightening downward) ---- */
    --f-display:'Bricolage','Georgia',serif;
    --f-ui:'Manrope',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    --f-data:'MartianMono','SFMono-Regular',ui-monospace,monospace;
    --t-hero:34px; --t-h1:25px; --t-h2:19px; --t-h3:15.5px;
    --t-body:13.5px; --t-sm:12.5px; --t-xs:11.5px; --t-micro:10.5px;

    /* ---- radii: one step smaller than the previous system; less bubble ---- */
    --r-xs:5px; --r-sm:8px; --r-md:11px; --r-lg:14px; --r-xl:20px; --r-pill:999px;

    /* ---- motion: one easing family, three durations ---- */
    --ease:cubic-bezier(.32,.72,0,1);          /* decelerate — the workhorse */
    --ease-in:cubic-bezier(.4,0,1,1);
    --ease-spring:cubic-bezier(.34,1.28,.55,1);
    --dur-1:.14s;  --dur-2:.26s;  --dur-3:.44s;

    /* ---- elevation: tinted with the brand hue, never neutral grey ---- */
    --sh-1:0 1px 2px hsl(var(--h-brand) 20% 12% / .05);
    --sh-2:0 2px 4px hsl(var(--h-brand) 20% 12% / .05), 0 8px 20px hsl(var(--h-brand) 20% 12% / .06);
    --sh-3:0 8px 18px hsl(var(--h-brand) 20% 12% / .10), 0 24px 56px hsl(var(--h-brand) 20% 12% / .12);
    --ring:0 0 0 3px hsl(var(--h-brand) 62% 30% / .22);

    --topbar-bg:#0E1512;
    --topbar-ink:#F2F5F2;
    --topbar-mute:#8FA096;

    /* Role identity is a single hue token consumed by a hairline and the role
       badge — never by the chrome itself. Repainting the whole topbar per role
       (as this previously did, inline) made the product look like five different
       applications and defeated theme switching. */
    --role:#2E7D63;

    color-scheme: light;
  }

  /* ---- DARK THEME — hand-tuned surfaces, not an inversion filter ------------
     Text inverts to a warm off-white; pure #FFF on near-black vibrates. Accents
     lighten because saturated dark greens disappear against a dark surface. ---- */
  :root[data-theme="dark"]{
    /* Surfaces step *up* in lightness with elevation, as they do on a real
       material. Previously paper (#151A18) and soft (#0F1412) sat 4 points apart,
       so a card on the page background lost its edge and tables read as a wash. */
    --paper:#1A211E;
    --soft:#0D110F;
    --softer:#232B27;
    --sunken:#070A09;
    --ink:#ECF1ED;
    --ink-2:#B9C4BC;
    --mute:#87958C;
    --faint:#63706A;
    --line:#28312C;
    --line-2:#1F2722;
    --line-strong:#3A453E;

    /* A dark surface needs a lighter accent, but #4FD39D at full chroma read as a
       different brand from the light theme's deep evergreen. Pulled toward the
       brand hue and desaturated ~18% — still AA on the surface, same family. */
    --accent:#3FBE8C;
    --accent-soft:#16302555;
    --accent-ink:#04120C;
    --accent-hover:#57D2A1;

    --ember:#FF8A4C;
    --ember-soft:#3A1F1145;

    /* Fully saturated red on near-black vibrates and pulls the eye off the data.
       Desaturated and lifted slightly. */
    --crit:#F0776B;   --crit-soft:#3A181655;
    --warn:#E8A93C;   --warn-soft:#33271445;
    --ok:#4FD39D;     --ok-soft:#12302345;
    --info:#5FB3E0;   --info-soft:#12293545;

    --band-high:#F0776B; --band-elev:#E8A93C; --band-mod:#D6C24A; --band-low:#3FBE8C;

    --sh-1:0 1px 2px rgb(0 0 0 / .40);
    --sh-2:0 2px 4px rgb(0 0 0 / .40), 0 8px 20px rgb(0 0 0 / .44);
    --sh-3:0 8px 18px rgb(0 0 0 / .50), 0 24px 56px rgb(0 0 0 / .55);
    --ring:0 0 0 3px hsl(var(--h-brand) 60% 55% / .30);

    --topbar-bg:#0A0E0C;
    --topbar-ink:#ECF1ED;
    --topbar-mute:#7B8981;

    --role:#4FD39D;

    color-scheme: dark;
  }

  /* Role hues — one family, differentiated by temperature rather than by
     unrelated colours. Each is legible on both themes. */
  :root[data-role="admin"]     { --role:#C2521B; }
  :root[data-role="buyer"]     { --role:#2E7D63; }
  :root[data-role="vrm"]       { --role:#1F6F8B; }
  :root[data-role="controller"]{ --role:#8A6A1F; }
  :root[data-role="exec"]      { --role:#5B4B8A; }
  :root[data-role="vendor"]    { --role:#5D6B72; }
  :root[data-theme="dark"][data-role="admin"]     { --role:#FF8A4C; }
  :root[data-theme="dark"][data-role="buyer"]     { --role:#4FD39D; }
  :root[data-theme="dark"][data-role="vrm"]       { --role:#5FB3E0; }
  :root[data-theme="dark"][data-role="controller"]{ --role:#E8C05A; }
  :root[data-theme="dark"][data-role="exec"]      { --role:#A594E0; }
  :root[data-theme="dark"][data-role="vendor"]    { --role:#93A3AB; }

  /* Orphaned tokens. An audit found 36 declarations referencing variables that were
     never defined — 19 `var(--dur)`, 5 `var(--dur-lg)`, 11 `var(--accent-2)` and one
     `var(--sh)`. An undefined custom property makes the whole declaration invalid, so
     those transitions and borders were silently doing nothing. Aliased here rather
     than rewritten at 36 call sites. */
  :root, :root[data-theme="dark"]{
    --dur:var(--dur-1);
    --dur-lg:var(--dur-3);
    --sh:var(--sh-2);
    --accent-2:color-mix(in srgb, var(--accent) 55%, var(--line));
  }

  /* legacy aliases — existing view markup keeps resolving while it migrates */
  :root, :root[data-theme="dark"]{
    --green:var(--accent); --green-d:var(--accent-hover); --navy:var(--info);
    --gold:var(--ember); --card:var(--paper); --mut:var(--mute); --moss:var(--ok);
    --amber:var(--warn); --rust:var(--crit);
    --high:var(--band-high); --elev:var(--band-elev); --mod:var(--band-mod); --low:var(--band-low);
  }


  /* ================= MOTION =================================================
     One easing family, three durations, and a rule: motion explains a change of
     state or position — it never decorates. Everything here is suppressed under
     prefers-reduced-motion at the foot of this block. */

  /* Views arrive with a short rise. 8px, not 24 — this is a work tool, and a
     large travel distance reads as latency once you have seen it fifty times. */
  @keyframes viewIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  #view > *{animation:viewIn var(--dur-2) var(--ease) both}

  /* Table rows: the whole row lifts toward the reader on hover rather than merely
     changing colour, so the click target is unambiguous in dense tables. */
  tbody tr{transition:background var(--dur-1) var(--ease), box-shadow var(--dur-1) var(--ease)}
  tbody tr:hover{background:var(--softer);box-shadow:inset 3px 0 0 var(--accent)}

  /* Cards settle rather than pop. */
  .card{transition:box-shadow var(--dur-2) var(--ease), border-color var(--dur-2) var(--ease),
        background var(--dur-2) var(--ease)}

  /* Primary actions depress on press — the one place a spring is warranted,
     because it maps to a physical button. */
  .btn{transition:transform var(--dur-1) var(--ease-spring), box-shadow var(--dur-1) var(--ease),
       background var(--dur-1) var(--ease), color var(--dur-1) var(--ease)}
  .btn:active{transform:scale(.975)}

  /* Focus is a ring that grows, so keyboard users see where they landed. */
  :where(a,button,input,select,textarea,[tabindex]):focus-visible{
    outline:none;box-shadow:var(--ring);border-radius:var(--r-xs);
    transition:box-shadow var(--dur-1) var(--ease)}

  /* Theme change crossfades the surfaces. Without this the switch is a hard cut
     that makes the whole product feel like it reloaded. */
  body,aside,main,.card,.topbar,table,th,td{
    transition:background-color var(--dur-2) var(--ease), color var(--dur-2) var(--ease),
               border-color var(--dur-2) var(--ease)}

  /* A critical band earns one slow pulse on arrival, then stops. Perpetual
     animation on a risk indicator becomes wallpaper within a day. */
  @keyframes critArrive{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--crit) 55%,transparent)}
                        70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
  .band.HIGH,.pill.crit{animation:critArrive 1.5s var(--ease) 1}

  /* Loading: a calm sweep, not a spinner-per-card. */
  @keyframes shimmer{from{background-position:-420px 0}to{background-position:420px 0}}
  .skeleton{background:linear-gradient(90deg,var(--softer) 0%,var(--soft) 45%,var(--softer) 90%);
    background-size:420px 100%;animation:shimmer 1.25s linear infinite;border-radius:var(--r-sm);
    color:transparent!important}

  @media (prefers-reduced-motion: reduce){
    #view > *,.band.HIGH,.pill.crit,.skeleton{animation:none!important}
    *,*::before,*::after{transition-duration:.01ms!important}
  }

  *{box-sizing:border-box;margin:0;padding:0}
  ::selection{background:color-mix(in srgb, var(--accent) 26%, transparent)}

  html{ -webkit-text-size-adjust:100%; }
  body{
    font-family:var(--f-ui);
    font-size:var(--t-body);
    line-height:1.5;
    letter-spacing:-.005em;
    font-variant-numeric: tabular-nums;   /* columns of figures must align */
    background:var(--soft);
    color:var(--ink);
    -webkit-font-smoothing:antialiased;
    -moz-osx-font-smoothing:grayscale;
    text-rendering:optimizeLegibility;
    transition:background var(--dur-2) var(--ease), color var(--dur-2) var(--ease);
  }
  h1,h2,h3,h4{
    font-family:var(--f-display);
    font-weight:600;
    letter-spacing:-.021em;
    line-height:1.16;
    font-optical-sizing:auto;
    color:var(--ink);
  }
  h1{font-size:var(--t-h1)} h2{font-size:var(--t-h2)} h3{font-size:var(--t-h3)}
  .mono,.card-label,.nav-group-label,.brand-sub,.kbd,code{
    font-family:var(--f-data); letter-spacing:-.02em; font-weight:500;
  }
  a{color:var(--accent);text-decoration:none;transition:color var(--dur-1) var(--ease)}
  a:hover{color:var(--accent-hover)}
  .hidden{display:none!important}

  /* focus: one visible, consistent ring — keyboard users are first-class */
  :where(a,button,input,select,textarea,[tabindex]):focus-visible{
    outline:none; box-shadow:var(--ring); border-radius:var(--r-sm);
  }

  /* ---- motion vocabulary ---- */
  @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  @keyframes fadeIn{from{opacity:0}to{opacity:1}}
  @keyframes growW{from{transform:scaleX(0)}to{transform:scaleX(1)}}
  @keyframes popIn{0%{opacity:0;transform:scale(.97) translateY(6px)}100%{opacity:1;transform:none}}
  @keyframes slideInRight{from{opacity:0;transform:translateX(18px)}to{opacity:1;transform:none}}
  @keyframes shimmer{0%{background-position:-420px 0}100%{background-position:420px 0}}
  @keyframes pulseRing{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 40%,transparent)}
                       70%{box-shadow:0 0 0 9px transparent}100%{box-shadow:0 0 0 0 transparent}}

  /* staggered entrance for lists and grids — content arrives, it doesn't blink in */
  .stagger > *{animation:fadeUp var(--dur-3) var(--ease) both}
  .stagger > *:nth-child(1){animation-delay:.02s}
  .stagger > *:nth-child(2){animation-delay:.05s}
  .stagger > *:nth-child(3){animation-delay:.08s}
  .stagger > *:nth-child(4){animation-delay:.11s}
  .stagger > *:nth-child(5){animation-delay:.14s}
  .stagger > *:nth-child(6){animation-delay:.17s}
  .stagger > *:nth-child(7){animation-delay:.19s}
  .stagger > *:nth-child(n+8){animation-delay:.21s}

  /* Respect the system setting. Motion is decoration; never a barrier. */
  @media (prefers-reduced-motion: reduce){
    *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;
      transition-duration:.01ms!important;scroll-behavior:auto!important}
  }
  /* ---- simple animations (engaging, not distracting) ---- */
  @keyframes popIn{0%{opacity:0;transform:scale(.96) translateY(8px)}100%{opacity:1;transform:none}}
  @keyframes slideInRight{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}
  @keyframes rowIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  @keyframes spin{to{transform:rotate(360deg)}}
  @keyframes pulseCrit{0%{box-shadow:0 0 0 0 rgba(217,83,79,.35)}70%{box-shadow:0 0 0 8px rgba(217,83,79,0)}100%{box-shadow:0 0 0 0 rgba(217,83,79,0)}}
  @keyframes bandPop{0%{transform:scale(.8);opacity:.4}100%{transform:scale(1);opacity:1}}
  table tr{animation:rowIn var(--dur) var(--ease) both}
  table tr:nth-child(2){animation-delay:.02s}table tr:nth-child(3){animation-delay:.04s}
  table tr:nth-child(4){animation-delay:.06s}table tr:nth-child(5){animation-delay:.08s}
  table tr:nth-child(6){animation-delay:.10s}table tr:nth-child(7){animation-delay:.12s}
  table tr:nth-child(n+8){animation-delay:.14s}
  .v360-panel,.rev-panel,.tier-card,.stat,.v360-attr{animation:popIn var(--dur-lg) var(--ease) both}
  .btn:active{transform:translateY(1px) scale(.985)}
  .btn{transition:transform var(--dur) var(--ease),background var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
  .btn:hover{box-shadow:0 2px 8px rgba(20,48,42,.14)}
  .modal,.modal-card,.sheet{animation:popIn var(--dur-lg) var(--ease) both}
  .flash,.toast{animation:slideInRight var(--dur-lg) var(--ease) both}
  .crit-band.on{animation:bandPop var(--dur-lg) var(--ease) both}
  .crit-band.on .crit-opt.sel{animation:pulseCrit 1.8s ease-out 1}
  .spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line);
        border-top-color:var(--green);border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px}
  #nav a{transition:background var(--dur) var(--ease),padding-left var(--dur) var(--ease)}
  #nav a:hover{padding-left:14px}
  .band,.posture-pill,.tag.crit{animation:bandPop var(--dur) var(--ease) both}
  @media (prefers-reduced-motion: reduce){
    *,#view>*,table tr,.v360-panel,.rev-panel,.tier-card,.stat,.v360-attr,.modal,.flash,.crit-band.on{
      animation:none!important;transition:none!important}
  }
  #view>*{animation:fadeUp var(--dur-lg) var(--ease) both}
  #view>*:nth-child(2){animation-delay:.04s} #view>*:nth-child(3){animation-delay:.08s}
  #view>*:nth-child(4){animation-delay:.12s} #view>*:nth-child(n+5){animation-delay:.16s}

  /* ============================================================================
     COMPONENT LAYER — every rule below reads from tokens, so both themes and any
     future palette change flow through without touching component code.
     ============================================================================ */
  #app{display:flex;flex-direction:column;height:100vh;max-height:100vh;overflow:hidden}

  /* ---- topbar: quieter than before. It is chrome, not content. ---- */
  .topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;justify-content:space-between;
    gap:16px;background:color-mix(in srgb, var(--topbar-bg) 88%, transparent);
    -webkit-backdrop-filter:saturate(180%) blur(22px);backdrop-filter:saturate(180%) blur(22px);
    color:var(--topbar-ink);padding:11px 20px;border-bottom:1px solid color-mix(in srgb,var(--accent) 22%,transparent);
    transition:background var(--dur-2) var(--ease)}
  /* Role identity: a 2px hairline in the role hue. Present enough to orient a user
     who holds several accounts, quiet enough that the product keeps one identity. */
  .topbar::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;
    background:linear-gradient(90deg,var(--role),color-mix(in srgb,var(--role) 30%,transparent) 62%,transparent);
    opacity:.9;transition:background var(--dur-2) var(--ease)}
  .topbar .brand{display:flex;align-items:center;gap:12px}
  .topbar .logo{width:34px;height:34px;border-radius:10px;
    background:linear-gradient(145deg, var(--accent), color-mix(in srgb,var(--accent) 60%, var(--ember)));
    color:var(--accent-ink);font-family:var(--f-display);font-weight:700;font-size:19px;
    display:flex;align-items:center;justify-content:center;letter-spacing:-.03em;
    box-shadow:inset 0 1px 0 rgb(255 255 255 / .22);transition:transform var(--dur-2) var(--ease-spring)}
  .topbar .logo:hover{transform:rotate(-4deg) scale(1.06)}
  .topbar .brand-name{font-size:17px;font-weight:600;letter-spacing:-.022em;font-family:var(--f-display)}
  .topbar .brand-sub{font-size:8.5px;color:var(--topbar-mute);margin-top:2px;letter-spacing:.16em;font-weight:500}
  .topbar-right{display:flex;align-items:center;gap:8px}
  .role-badge{display:flex;align-items:center;gap:8px;background:rgb(255 255 255 / .07);
    border:1px solid rgb(255 255 255 / .10);border-radius:var(--r-sm);padding:5px 11px}
  .role-badge .role-ico{display:flex;opacity:.85}
  .role-badge .role-name{font-size:12.5px;font-weight:600}
  .role-badge .role-kind{font-size:9.5px;color:var(--topbar-mute);letter-spacing:.08em;font-family:var(--f-data)}
  .signout,.help-btn,.nav-toggle{color:var(--topbar-ink);background:rgb(255 255 255 / .08);
    border:1px solid rgb(255 255 255 / .07);border-radius:var(--r-sm);font-size:12px;font-weight:600;
    cursor:pointer;transition:background var(--dur-1) var(--ease),transform var(--dur-1) var(--ease)}
  .signout{padding:6px 12px} .help-btn{padding:6px 11px;display:flex;align-items:center;gap:6px}
  .nav-toggle{width:32px;height:32px;display:flex;align-items:center;justify-content:center}
  .signout:hover{background:var(--crit);border-color:transparent}
  .help-btn:hover,.nav-toggle:hover{background:rgb(255 255 255 / .16)}
  .signout:active,.help-btn:active,.nav-toggle:active{transform:scale(.96)}

  /* ---- theme switch: a real control, not a hidden preference ---- */
  .theme-switch{position:relative;width:52px;height:28px;border-radius:var(--r-pill);cursor:pointer;
    background:rgb(255 255 255 / .10);border:1px solid rgb(255 255 255 / .12);padding:0;flex-shrink:0;
    transition:background var(--dur-2) var(--ease)}
  .theme-switch:hover{background:rgb(255 255 255 / .18)}
  .theme-switch .knob{position:absolute;top:2px;left:2px;width:22px;height:22px;border-radius:50%;
    background:linear-gradient(150deg,#FFF5E2,#F2D9A8);display:flex;align-items:center;justify-content:center;
    transition:transform var(--dur-2) var(--ease-spring),background var(--dur-2) var(--ease);
    box-shadow:0 1px 3px rgb(0 0 0 / .3)}
  :root[data-theme="dark"] .theme-switch .knob{transform:translateX(24px);
    background:linear-gradient(150deg,#5A6B62,#2E3A34)}
  .theme-switch .knob svg{width:12px;height:12px;stroke:#0E1512;stroke-width:2;fill:none;
    transition:opacity var(--dur-1) var(--ease)}
  :root[data-theme="dark"] .theme-switch .knob svg{stroke:#ECF1ED}
  .theme-switch .ico-sun{display:block} .theme-switch .ico-moon{display:none}
  :root[data-theme="dark"] .theme-switch .ico-sun{display:none}
  :root[data-theme="dark"] .theme-switch .ico-moon{display:block}

  /* ---- sidebar ---- */
  .shell{display:flex;flex:1;min-height:0;overflow:hidden}
  aside{width:224px;background:var(--paper);border-right:1px solid var(--line);padding:14px 9px;
    flex-shrink:0;overflow-y:auto;overscroll-behavior:contain;
    transition:width var(--dur-2) var(--ease),padding var(--dur-2) var(--ease),background var(--dur-2) var(--ease)}
  aside::-webkit-scrollbar,main::-webkit-scrollbar{width:8px}
  aside::-webkit-scrollbar-thumb,main::-webkit-scrollbar-thumb{
    background:color-mix(in srgb,var(--mute) 30%,transparent);border-radius:8px;
    border:2px solid transparent;background-clip:content-box}
  aside::-webkit-scrollbar-thumb:hover,main::-webkit-scrollbar-thumb:hover{
    background:color-mix(in srgb,var(--mute) 55%,transparent);background-clip:content-box}
  aside,main{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--mute) 34%,transparent) transparent}
  .nav-group{margin-bottom:11px}
  .nav-group-label{font-size:9.5px;font-weight:600;color:var(--faint);text-transform:uppercase;
    padding:5px 9px;letter-spacing:.13em;cursor:pointer;user-select:none;border-radius:var(--r-xs);
    display:flex;align-items:center;gap:7px;transition:color var(--dur-1) var(--ease)}
  .nav-group-label:hover{color:var(--ink-2)}
  .nav-group-label::before{content:"";width:5px;height:5px;border-right:1.5px solid currentColor;
    border-bottom:1.5px solid currentColor;transform:rotate(45deg) translateY(-1px);
    transition:transform var(--dur-2) var(--ease);flex-shrink:0}
  .nav-group.collapsed .nav-group-label::before{transform:rotate(-45deg) translateX(-1px)}
  .nav-group.collapsed a,.nav-group.collapsed select{display:none!important}

  /* nav links: icon slot is a fixed 18px box so labels align on a true grid */
  aside a{display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:var(--r-sm);
    color:var(--ink-2);font-size:12.8px;font-weight:500;position:relative;
    transition:background var(--dur-1) var(--ease),color var(--dur-1) var(--ease)}
  aside a .ico{width:18px;height:18px;flex-shrink:0;display:flex;align-items:center;justify-content:center;
    opacity:.72;transition:opacity var(--dur-1) var(--ease),transform var(--dur-2) var(--ease-spring)}
  aside a .ico svg{width:16px;height:16px;stroke:currentColor;stroke-width:1.6;fill:none;
    stroke-linecap:round;stroke-linejoin:round}
  aside a:hover{background:var(--softer);color:var(--ink)}
  aside a:hover .ico{opacity:1;transform:scale(1.09)}
  aside a.active{background:var(--accent-soft);color:var(--accent);font-weight:650}
  aside a.active .ico{opacity:1}
  aside a.active::before{content:"";position:absolute;left:-9px;top:50%;transform:translateY(-50%);
    width:3px;height:17px;border-radius:0 3px 3px 0;background:var(--accent);
    animation:growH var(--dur-2) var(--ease) both}
  @keyframes growH{from{height:0;opacity:0}to{height:17px;opacity:1}}

  #view{flex:1 1 auto;min-width:0;animation:fadeIn var(--dur-2) var(--ease)}
  #app.nav-hidden aside{width:0;padding-left:0;padding-right:0;border:none;overflow:hidden}

  /* ---- page header ---- */
  .top{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap;margin-bottom:18px}
  .top h1{font-size:var(--t-h1);letter-spacing:-.028em}
  .top .sub{color:var(--mute);font-size:var(--t-sm);margin-top:5px;max-width:62ch;line-height:1.5}
  .top > div:first-child{flex:1;min-width:220px}

  /* ---- surfaces ---- */
  .card{background:var(--paper);border:1px solid var(--line);border-radius:var(--r-md);padding:16px;
    box-shadow:var(--sh-1);
    transition:box-shadow var(--dur-2) var(--ease),border-color var(--dur-2) var(--ease),
               transform var(--dur-2) var(--ease),background var(--dur-2) var(--ease)}
  .card.click:hover,.card[onclick]:hover{box-shadow:var(--sh-2);border-color:var(--line-strong);
    transform:translateY(-2px);cursor:pointer}
  .card-label{font-size:var(--t-micro);text-transform:uppercase;letter-spacing:.12em;color:var(--faint);
    font-weight:600;margin-bottom:6px}
  .muted,.mut{color:var(--mute)}
  .note{border-left:3px solid var(--accent);background:var(--accent-soft);padding:10px 13px;
    border-radius:0 var(--r-sm) var(--r-sm) 0;font-size:var(--t-sm);color:var(--ink-2)}
  .err{border-left:3px solid var(--crit);background:var(--crit-soft);padding:10px 13px;
    border-radius:0 var(--r-sm) var(--r-sm) 0;color:var(--crit);font-size:var(--t-sm)}
  .warn{border-left:3px solid var(--warn);background:var(--warn-soft);padding:10px 13px;
    border-radius:0 var(--r-sm) var(--r-sm) 0;color:var(--ink-2);font-size:var(--t-sm)}

  /* ---- tables: denser rows, quiet grid, sticky head ---- */
  table{width:100%;border-collapse:separate;border-spacing:0;font-size:var(--t-sm)}
  th{background:var(--softer);color:var(--faint);text-align:left;padding:8px 12px;font-weight:600;
    font-size:var(--t-micro);text-transform:uppercase;letter-spacing:.1em;
    border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2;
    font-family:var(--f-data)}
  th:first-child{border-top-left-radius:var(--r-sm)} th:last-child{border-top-right-radius:var(--r-sm)}
  td{padding:9px 12px;border-bottom:1px solid var(--line-2);vertical-align:middle;color:var(--ink-2)}
  tbody tr{transition:background var(--dur-1) var(--ease)}
  tbody tr:hover td{background:var(--softer)}
  tr.click{cursor:pointer}
  tr.click:hover td{background:var(--accent-soft)}
  td b,td strong{color:var(--ink);font-weight:600}
  .id,td .id{font-family:var(--f-data);font-size:11px;letter-spacing:-.03em;color:var(--ink-2)}

  /* ---- buttons: one shape language ---- */
  .btn{background:var(--accent);color:var(--accent-ink);border:1px solid transparent;
    border-radius:var(--r-sm);padding:8px 15px;font-size:var(--t-sm);font-weight:600;cursor:pointer;
    font-family:var(--f-ui);display:inline-flex;align-items:center;gap:7px;letter-spacing:-.01em;
    transition:background var(--dur-1) var(--ease),transform var(--dur-1) var(--ease),
               box-shadow var(--dur-1) var(--ease)}
  .btn:hover{background:var(--accent-hover);box-shadow:var(--sh-2)}
  .btn:active{transform:scale(.975)}
  .btn.ghost{background:transparent;color:var(--ink-2);border-color:var(--line-strong)}
  .btn.ghost:hover{background:var(--softer);color:var(--ink);border-color:var(--mute);box-shadow:none}
  .btn.sm{padding:5px 10px;font-size:var(--t-xs)}
  .btn.danger{background:var(--crit)} .btn.danger:hover{background:var(--crit);filter:brightness(1.12)}
  .btn:disabled{opacity:.45;cursor:not-allowed;transform:none}

  /* ---- inputs ---- */
  input,select,textarea{font-family:var(--f-ui);font-size:var(--t-sm);color:var(--ink);
    background:var(--paper);border:1px solid var(--line-strong);border-radius:var(--r-sm);
    padding:8px 11px;width:100%;
    transition:border-color var(--dur-1) var(--ease),box-shadow var(--dur-1) var(--ease),
               background var(--dur-2) var(--ease)}
  input::placeholder,textarea::placeholder{color:var(--faint)}
  input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:var(--ring)}
  .field{margin-bottom:12px}
  .field label{display:block;font-size:var(--t-xs);font-weight:600;color:var(--ink-2);margin-bottom:5px}
  /* checkbox + label on one baseline — previously the box floated away from its text */
  .field label:has(input[type=checkbox]),label.check{display:flex;align-items:center;gap:9px;
    font-weight:500;font-size:var(--t-sm);color:var(--ink-2);cursor:pointer}
  input[type=checkbox],input[type=radio]{width:16px;height:16px;flex:0 0 16px;accent-color:var(--accent);
    cursor:pointer;margin:0}

  /* ---- pills, tags, bands ---- */
  .tag,.pill{display:inline-flex;align-items:center;gap:5px;padding:2.5px 9px;border-radius:var(--r-pill);
    font-size:var(--t-micro);font-weight:600;letter-spacing:.02em;background:var(--softer);color:var(--ink-2)}
  .pill.crit,.tag.crit{background:var(--crit-soft);color:var(--crit)}
  .pill.warn,.tag.warn{background:var(--warn-soft);color:var(--warn)}
  .pill.ok,.tag.ok{background:var(--ok-soft);color:var(--ok)}
  .band{display:inline-flex;align-items:center;padding:2.5px 9px;border-radius:var(--r-pill);
    font-size:var(--t-micro);font-weight:700;letter-spacing:.05em;font-family:var(--f-data)}
  .band.HIGH{background:var(--crit-soft);color:var(--band-high)}
  .band.ELEVATED{background:var(--warn-soft);color:var(--band-elev)}
  .band.MODERATE{background:var(--warn-soft);color:var(--band-mod)}
  .band.LOW{background:var(--ok-soft);color:var(--band-low)}

  /* ---- modal ---- */
  .ovl{position:fixed;inset:0;background:color-mix(in srgb, var(--sunken) 62%, transparent);
    -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);z-index:120;display:flex;
    align-items:center;justify-content:center;padding:24px;animation:fadeIn var(--dur-2) var(--ease)}
  .modal{background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);padding:22px;
    box-shadow:var(--sh-3);max-width:560px;width:100%;max-height:86vh;overflow:auto;
    animation:popIn var(--dur-3) var(--ease-spring) both}
  .modal.full{max-width:1080px}
  .modal h3{font-size:var(--t-h2);margin-bottom:5px}

  /* ---- skeleton loading: shape of the content, not a spinner ---- */
  /* row affordance: the whole row is the target; the chevron only hints at it */
  .row-go{display:inline-flex;color:var(--faint);opacity:0;transform:translateX(-4px);
    transition:opacity var(--dur-1) var(--ease),transform var(--dur-1) var(--ease)}
  tr:hover .row-go{opacity:1;transform:none;color:var(--accent)}

  .skel{background:linear-gradient(90deg,var(--softer) 25%,var(--sunken) 37%,var(--softer) 63%);
    background-size:840px 100%;animation:shimmer 1.4s linear infinite;border-radius:var(--r-xs);
    height:12px;margin:7px 0}

  .home-theme-label{font-family:var(--f-display);font-weight:600;font-size:15px;color:var(--ink);margin:20px auto 10px;max-width:1100px;letter-spacing:.01em;display:flex;align-items:center;gap:12px}
  .home-theme-label::after{content:"";flex:1;height:1px;background:var(--line)}
  .help-btn{background:rgba(255,255,255,.1);border:none;color:#fff;border-radius:10px;padding:7px 12px;font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px}
  .help-btn:hover{background:rgba(216,169,74,.3)}
  .help-overlay{position:fixed;inset:0;background:rgba(11,14,12,.34);z-index:120;opacity:0;pointer-events:none;transition:opacity .25s}
  .help-overlay.open{opacity:1;pointer-events:auto}
  .help-drawer{position:fixed;top:0;right:0;height:100%;width:420px;max-width:92vw;background:var(--paper);z-index:121;box-shadow:-12px 0 40px rgba(0,0,0,.22);transform:translateX(100%);transition:transform .28s cubic-bezier(.2,.7,.2,1);display:flex;flex-direction:column}
  .help-drawer.open{transform:none}
  .help-head{background:linear-gradient(135deg,var(--ink),var(--accent));color:#fff;padding:18px 20px}
  .help-head h3{font-family:var(--f-display);font-size:20px;margin:0}
  .help-head .hsub{color:var(--faint);font-size:12px;margin-top:4px}
  .help-head .hx{position:absolute;top:14px;right:16px;background:rgba(255,255,255,.14);border:none;color:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;font-size:16px}
  .help-body{padding:18px 20px;overflow-y:auto;flex:1}
  .help-purpose{font-size:13.5px;color:var(--ink-2);background:var(--warn-soft);border-left:3px solid var(--gold,var(--ember));border-radius:0 8px 8px 0;padding:12px 14px;margin-bottom:16px}
  .help-dp{border-bottom:1px solid var(--line);padding:10px 0}
  .help-dp .term{font-weight:600;color:var(--accent);font-size:13.5px}
  .help-dp .def{font-size:12.8px;color:var(--mute);margin-top:2px}
  .help-sec{font-family:var(--f-data);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--warn);margin:16px 0 6px}
  .input-invalid{border-color:var(--crit)!important;background:var(--crit-soft)!important}
  .input-err-msg{color:var(--crit);font-size:11px;margin-top:3px}
  .ccy-select{font-size:12px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--paper)}
  /* ===== 60-second cinematic demo (#6) ===== */
  .demo-launch{margin-top:20px;background:linear-gradient(135deg,#E2BD86,var(--ember) 60%,#A87E45);color:#0B0E0C;border:none;border-radius:14px;padding:13px 24px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 8px 24px rgba(201,155,95,.35);display:inline-flex;align-items:center;gap:9px;font-family:var(--f-ui);transition:transform .15s,box-shadow .15s}
  .demo-launch:hover{transform:translateY(-1px);box-shadow:0 12px 30px rgba(201,155,95,.48)}
  .demo-overlay{position:fixed;inset:0;z-index:200;background:radial-gradient(1200px 720px at 50% -12%,#16302a,#0b1410 72%);display:flex;flex-direction:column;opacity:0;transition:opacity .4s;font-family:var(--f-ui)}
  .demo-overlay.open{opacity:1}
  .demo-top{position:relative;padding:24px 36px 4px;color:#fff}
  .demo-kicker{font-family:var(--f-data);font-size:11px;letter-spacing:.24em;color:var(--ember);text-transform:uppercase}
  .demo-h{font-family:var(--f-display);font-size:26px;font-weight:600;margin:5px 0 0;letter-spacing:-.01em}
  .demo-x{position:absolute;top:22px;right:28px;background:rgba(255,255,255,.12);border:none;color:#fff;width:38px;height:38px;border-radius:10px;font-size:16px;cursor:pointer}
  .demo-x:hover{background:rgba(255,255,255,.22)}
  .demo-timeline{display:flex;gap:10px;margin:18px 36px 0}
  .demo-seg{flex:1;display:flex;flex-direction:column;gap:7px;cursor:pointer}
  .demo-seg .bar{height:5px;border-radius:3px;background:rgba(255,255,255,.15);overflow:hidden}
  .demo-seg .bar i{display:block;height:100%;width:0;background:var(--ember);border-radius:3px}
  .demo-seg .lab{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#92a399;font-family:var(--f-data);transition:color .3s}
  .demo-seg.active .lab{color:#fff}
  .demo-stage-wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:18px 36px;min-height:0}
  .demo-stage{width:100%;max-width:1000px;transition:opacity .32s ease,transform .32s ease}
  .demo-stage.swap{opacity:0;transform:translateY(8px)}
  .demo-frame{background:#FAF8F2;border-radius:16px;box-shadow:0 30px 90px rgba(0,0,0,.5);overflow:hidden;border:1px solid rgba(255,255,255,.08)}
  .demo-frame .tb{display:flex;align-items:center;gap:7px;padding:11px 16px}
  .demo-frame .tb .dot{width:10px;height:10px;border-radius:50%}
  .demo-frame .tb .ttl{color:#fff;font-size:13px;font-weight:600;margin-left:7px}
  .demo-frame .tb .badge{margin-left:auto;font-size:10.5px;font-family:var(--f-data);padding:3px 10px;border-radius:20px;background:rgba(255,255,255,.18);color:#fff}
  .demo-body{padding:22px 26px;min-height:312px}
  .demo-stitle{font-family:var(--f-display);font-size:19px;font-weight:600;color:var(--ink);margin-bottom:14px}
  .d-rise{opacity:0;animation:dRise .55s cubic-bezier(.2,.7,.2,1) forwards;animation-delay:var(--d,0ms)}
  .d-pop{opacity:0;animation:dPop .5s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:var(--d,0ms)}
  @keyframes dRise{from{opacity:0;transform:translateY(13px)}to{opacity:1;transform:none}}
  @keyframes dPop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}
  .demo-field{display:flex;justify-content:space-between;gap:14px;padding:9px 13px;border:1px solid var(--line);border-radius:9px;margin-bottom:8px;background:var(--paper);font-size:13.5px}
  .demo-field .k{color:#8a8472;font-size:10.5px;font-family:var(--f-data);text-transform:uppercase;letter-spacing:.06em;align-self:center}
  .demo-field .v{font-weight:600;color:#1A2A22}
  .dcard{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .dcard .k{color:#8a8472;font-size:10.5px;font-family:var(--f-data);text-transform:uppercase;letter-spacing:.07em}
  .demo-stat{font-family:var(--f-display);font-size:30px;font-weight:600;line-height:1.1;margin:4px 0}
  .demo-bar{height:9px;background:#ece6d6;border-radius:6px;overflow:hidden}
  .demo-bar i{display:block;height:100%;width:0;border-radius:6px;transition:width 1.1s cubic-bezier(.2,.7,.2,1)}
  .demo-cap-wrap{padding:0 36px 6px}
  .demo-cap{max-width:1000px;margin:0 auto;color:#dfe6dc;font-size:15.5px;line-height:1.5;min-height:48px}
  .demo-cap b{color:#fff;font-weight:600}
  .demo-controls{display:flex;align-items:center;justify-content:center;gap:18px;padding:10px 0 28px;position:relative}
  .demo-btn{background:rgba(255,255,255,.12);border:none;color:#fff;width:46px;height:46px;border-radius:50%;font-size:17px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:filter .15s}
  .demo-btn.play{width:58px;height:58px;background:var(--ember);color:#0B0E0C;font-size:20px}
  .demo-btn:hover{filter:brightness(1.14)}
  .demo-time{position:absolute;right:36px;bottom:38px;color:#92a399;font-family:var(--f-data);font-size:12px}
  .demo-pill{display:inline-block;font-size:11px;font-family:var(--f-data);padding:3px 10px;border-radius:20px}
  .d-fade{opacity:0;animation:dFade .55s ease forwards;animation-delay:var(--d,0ms)}
  @keyframes dFade{to{opacity:1}}
  @keyframes dPulse{0%,100%{r:13}50%{r:17}}
  .d-hot{animation:dPulse 1.6s ease-in-out infinite}
  .navsort-row{display:flex;align-items:center;gap:6px;padding:6px 8px;margin:3px 0;background:var(--paper);border:1px solid var(--line);border-radius:6px;font-size:12px;cursor:grab;user-select:none}
  .navsort-row.dragging{opacity:.4;border-color:var(--gold,var(--ember))}
  .navsort-row .grip{color:#bbb}
  .navsort-items{min-height:28px;padding:2px 0;border-radius:6px}
  .navsort-items.drop-target{background:#F3F8F5;outline:1px dashed var(--gold,var(--ember))}
  .navsort-items:empty::after{content:'drop items here';display:block;color:#bbb;font-size:11px;font-style:italic;padding:6px 8px}
  .lang-select{width:calc(100% - 20px);margin:0 10px 6px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--paper);font:inherit;font-size:12px;color:var(--ink,var(--ink));cursor:pointer}
  nav a{display:flex;align-items:center;gap:11px;width:100%;text-align:left;padding:9px 11px;border-radius:10px;
        color:var(--ink-2);font-size:14px;font-weight:450;cursor:pointer;position:relative;
        transition:background var(--dur) var(--ease),color var(--dur) var(--ease)}
  nav a:hover{background:var(--softer)}
  nav a.active{background:var(--paper);color:var(--accent);font-weight:600;box-shadow:var(--sh-1)}
  nav a.active::before{content:"";position:absolute;left:-1px;top:50%;transform:translateY(-50%);width:3px;height:18px;border-radius:3px;background:var(--accent)}
  nav .ico{font-size:16px;width:20px;text-align:center;flex:none}

  main{flex:1;padding:28px 32px;overflow-y:auto;overscroll-behavior:contain;min-width:0;max-width:1280px}
  .top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
       flex-wrap:wrap;margin-bottom:22px}
  .top h1{font-family:var(--f-display);font-size:var(--t-h1);font-weight:600;
          letter-spacing:-.028em;line-height:1.08}
  /* 62ch, not 680px: the measure should follow the type size, and a 3-line
     subtitle in a narrow column beside empty space is a layout failure. */
  .top .sub{color:var(--mute);font-size:var(--t-sm);margin-top:6px;max-width:62ch;line-height:1.5}
  .top > div:first-child{flex:1 1 320px;min-width:0}
  /* Actions group to the right and stay on one line where they fit. */
  .top .actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}

  /* --accent-ink, not #fff: in the dark theme the accent lightens to a mint, and
     white-on-mint measures ~1.9:1 — unreadable. The token pairs correctly in both. */
  .btn{background:var(--accent);color:var(--accent-ink);border:none;padding:11px 17px;border-radius:var(--r-sm);
       font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;
       transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),background var(--dur) var(--ease);
       box-shadow:0 1px 2px rgba(26,77,60,.2)}
  .btn:hover{background:#196046;transform:translateY(-1px);box-shadow:0 5px 16px rgba(26,77,60,.28)}
  .btn:active{transform:translateY(0)}
  .btn:disabled{opacity:.45;cursor:not-allowed;box-shadow:none;transform:none}
  .btn.ghost{background:transparent;color:var(--ink-2);border:1px solid var(--line-strong);box-shadow:none}
  .btn.ghost:hover{border-color:var(--mute);background:var(--softer);color:var(--ink)}
  .btn.amber{background:var(--warn)} .btn.sm{padding:7px 12px;font-size:12px}

  .grid{display:grid;gap:14px}
  .g4{grid-template-columns:repeat(4,1fr)} .g3{grid-template-columns:repeat(3,1fr)}
  .g2{grid-template-columns:repeat(2,1fr)}
  .card{background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);padding:24px;
        box-shadow:var(--sh-1);transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
  .card:hover{box-shadow:var(--sh-2)}
  .stat{position:relative;overflow:hidden;text-align:left}
  .stat .v{font-family:var(--f-display);font-size:30px;font-weight:600;color:var(--accent);line-height:1}
  .stat .l{font-size:12px;letter-spacing:.02em;color:var(--mute);font-weight:500;margin-top:7px}

  .sec-h{display:flex;align-items:center;gap:10px;margin:26px 0 14px}
  .sec-h h2{font-size:18px;font-weight:600} .sec-h .rule{flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent)}

  table{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--line);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--sh-1)}
  th{background:var(--softer);color:var(--ink-2);text-align:left;padding:11px 16px;font-size:11px;letter-spacing:.04em;text-transform:uppercase;font-weight:600;font-family:var(--f-data)}
  td{padding:12px 16px;border-bottom:1px solid var(--line-2);font-size:13.5px}
  tr:last-child td{border-bottom:none}
  tr.click{cursor:pointer;transition:background var(--dur) var(--ease)} tr.click:hover td{background:var(--soft)}

  .band{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;color:#fff}
  .band.HIGH{background:var(--crit)} .band.ELEVATED{background:var(--warn)}
  .band.MODERATE{background:var(--mod)} .band.LOW{background:var(--ok)}
  .tag{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:var(--softer);color:var(--ink-2)}
  .crit{background:#f7e6e3;color:var(--crit)}

  /* ---- analysis sections (FDD / Reputation / Monitoring / Contracts) ---- */
  .seg{display:inline-flex;gap:4px;background:var(--sunken);border:1px solid var(--line);
       border-radius:var(--r-md);padding:4px;margin-bottom:16px;flex-wrap:wrap;max-width:100%}
  .seg button{flex:0 1 auto;min-width:120px;border:none;background:transparent;padding:8px 10px;border-radius:7px;
        font-family:inherit;font-size:12.5px;font-weight:600;color:var(--mut);cursor:pointer;transition:.15s}
  .seg button.on{background:var(--paper);color:var(--accent);box-shadow:var(--sh-1)}
  /* ---- CR-9 Critical top band ---- */
  .crit-band{display:flex;justify-content:space-between;align-items:center;gap:16px;
        background:#f6f4ec;border:1px solid var(--line);border-left:4px solid #9aa6a0;
        border-radius:12px;padding:14px 18px;margin-bottom:16px;transition:.25s}
  .crit-band.on{background:linear-gradient(90deg,#fbe7e6,#f7f1ea);border-left-color:#d9534f}
  .crit-band-label{font-family:var(--f-display);font-size:16px;font-weight:600;color:var(--ink)}
  .crit-band-sub{display:block;font-size:11.5px;color:var(--mut);margin-top:2px;max-width:620px}
  .crit-toggle{display:flex;gap:4px;background:var(--paper);border:1px solid var(--line);border-radius:9px;padding:3px}
  .crit-opt{border:none;background:transparent;padding:7px 18px;border-radius:7px;font-family:inherit;
        font-size:13px;font-weight:700;color:var(--mut);cursor:pointer;transition:.18s}
  .crit-opt.sel{background:var(--green);color:#fff}
  .crit-band.on .crit-opt.sel{background:#d9534f}
  /* ---- CR-10 risk attributes panel on 360 ---- */
  .v360-attr-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .v360-attr{background:#faf9f4;border:1px solid var(--line);border-radius:10px;padding:11px 13px}
  .v360-attr .al{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
  .v360-attr .av{font-family:var(--f-display);font-size:15px;font-weight:600;color:var(--ink);margin-top:3px}
  .v360-attr .as{font-size:11px;color:var(--mut);margin-top:2px}
  /* ---- CR-2 assessment review ---- */
  .rev-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
  .rev-panel{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px}
  .rev-panel h3{font-size:12.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--green);margin:0 0 12px}
  .rev-row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #f0ede4;font-size:13px}
  .rev-row:last-child{border-bottom:none}
  .rev-row .rk{color:var(--mut)}.rev-row .rv{font-weight:600;color:var(--ink);text-align:right;max-width:60%}
  .rev-risk{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px solid #f0ede4;font-size:13px}
  .rev-risk:last-child{border-bottom:none}
  .rev-stage{margin-bottom:12px}
  .rev-stage-h{font-size:12px;font-weight:700;color:var(--green);margin-bottom:5px}
  .rev-turn{font-size:12px;color:#43504a;padding:4px 0 4px 10px;border-left:2px solid #e6e2d6;margin-bottom:3px}
  .rev-verdict{margin-top:10px;padding:10px 12px;background:#f6f4ec;border-radius:9px;font-size:12.5px;color:#3a463f;white-space:pre-wrap}
  .rev-gaps{margin-top:10px;font-size:12px;color:#9a6a1a;background:#fbf2d6;padding:9px 11px;border-radius:8px}
  /* supply-chain concentration legend */
  .conc-legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:11.5px;color:var(--mut)}
  .conc-legend i.cdot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
  .v360-hero{background:linear-gradient(135deg,var(--ink) 0%,#1d4a40 100%);color:#f4f1e8;border-radius:16px;
        padding:24px 26px;margin-bottom:18px;position:relative;overflow:hidden}
  .v360-hero .vname{font-family:var(--f-display);font-size:24px;font-weight:600;letter-spacing:-.01em}
  .v360-hero .vmeta{font-size:12.5px;opacity:.82;margin-top:3px}
  .v360-verdict{display:flex;align-items:center;gap:16px;margin-top:18px}
  .v360-dot{width:54px;height:54px;border-radius:50%;flex-shrink:0;box-shadow:0 0 0 5px rgba(255,255,255,.12)}
  .v360-dot.l0{background:#4caf7e}.v360-dot.l1{background:#d9b441}.v360-dot.l2{background:#e08a3c}.v360-dot.l3{background:#d9534f}
  .v360-vlabel{font-family:var(--f-display);font-size:21px;font-weight:600}
  .v360-vsub{font-size:12px;opacity:.8}
  .v360-crit{position:absolute;top:18px;right:22px;background:var(--gold);color:var(--ink);font-size:11px;
        font-weight:700;padding:5px 11px;border-radius:20px;letter-spacing:.03em}
  .v360-dims{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}
  .v360-dim{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:13px 12px;text-align:center}
  .v360-dim .dv{font-family:var(--f-display);font-size:18px;font-weight:600;color:var(--green)}
  .v360-dim .dl{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-top:4px}
  .v360-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
  .v360-panel{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px}
  .v360-panel h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 12px}
  .v360-metric{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f0ede4;font-size:13px}
  .v360-metric:last-child{border-bottom:none}
  .v360-metric .mk{color:var(--mut)}.v360-metric .mv{font-weight:600;color:var(--ink)}
  .v360-exc{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid #f0ede4;font-size:13px}
  .v360-exc:last-child{border-bottom:none}
  .v360-sevdot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
  .sev-Critical{background:#d9534f}.sev-High{background:#e08a3c}.sev-Medium{background:#d9b441}.sev-Low{background:#7a8c84}
  .v360-bar{height:8px;border-radius:5px;background:#eee;overflow:hidden;margin-top:6px}
  .v360-bar span{display:block;height:100%}
  .port-row{display:grid;grid-template-columns:1.6fr .7fr .9fr .8fr .6fr;gap:10px;align-items:center;
        padding:11px 14px;border:1px solid var(--line);border-radius:10px;margin-bottom:7px;background:var(--paper);cursor:pointer;transition:.12s}
  .port-row:hover{border-color:var(--green);box-shadow:0 2px 8px rgba(20,48,42,.08)}
  .posture-pill{font-size:11px;font-weight:700;padding:4px 9px;border-radius:14px;text-align:center}
  .pp-0{background:#e3f3ea;color:#1f7a4d}.pp-1{background:#fbf2d6;color:#94701a}
  .pp-2{background:#fbe7d4;color:#a85a1e}.pp-3{background:#f7dcda;color:#a5322e}
  .ent-box{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
  .ent-box .row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .score-strip{display:flex;gap:20px;align-items:center;margin-bottom:18px;flex-wrap:wrap}
  .score-big{text-align:center;min-width:120px}
  .score-num{font-family:var(--f-display);font-size:46px;font-weight:900;line-height:1;color:var(--green)}
  .score-cap{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.1em;margin-top:4px}
  .altman{display:flex;flex-direction:column;gap:4px}
  .altman-z{font-size:15px} .altman-z b{font-size:20px;margin-left:6px}
  .pillar-row{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:16px}
  .pillar-row.wrap{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
  .gauge{display:flex;flex-direction:column;gap:6px;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:12px}
  .gauge-bar{height:9px;background:#efece2;border-radius:6px;overflow:hidden}
  .gauge-fill{height:100%;border-radius:6px;transition:width .7s cubic-bezier(.16,.84,.44,1)}
  .gauge-fill.ok{background:var(--moss)} .gauge-fill.info{background:var(--navy)}
  .gauge-fill.warn{background:var(--amber)} .gauge-fill.crit{background:var(--rust)}
  .gauge-meta{display:flex;justify-content:space-between;font-size:11.5px}
  .gauge-meta .gl{color:var(--mut)} .gauge-meta .gv{font-weight:700}
  .tier-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
  .tier-card{border-radius:11px;padding:14px;border:1px solid var(--line)}
  .tier-card.crit{background:#f9ece9} .tier-card.warn{background:#f8f0e2}
  .tier-card.info{background:#eaf0f4} .tier-card.mute{background:#f1efe8}
  .tier-no{font-size:10px;font-weight:800;letter-spacing:.08em;color:var(--mut)}
  .tier-card p{margin-top:6px;font-size:12px;color:var(--mut)}
  .prov{margin-top:14px;border:1px solid var(--line);border-radius:12px;padding:15px;background:var(--paper)}
  .prov-head{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:14px}
  .prov-meta{font-size:12.5px;color:var(--mut);margin-top:7px}
  .ai-out{background:var(--paper);border:1px solid var(--line);border-radius:11px;padding:16px;margin-top:12px;font-size:13.5px;line-height:1.6;white-space:pre-wrap}
  .stress-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:12px}
  .stress-grid input[type=range]{width:100%}
  .pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}
  .pill.ok{background:#e3efe6;color:var(--moss)} .pill.info{background:#e7eef3;color:var(--navy)}
  .pill.warn{background:#f6ebda;color:var(--amber)} .pill.crit{background:#f6e2de;color:var(--rust)}
  .pill.mute{background:#eee;color:var(--mut)}
  .empty-box{text-align:center;padding:38px;color:var(--mut)}
  .empty-box .ei{font-size:34px;margin-bottom:8px} .empty-box .et{font-weight:700;color:var(--ink);font-size:15px}

  /* forms */
  .field{margin-bottom:13px;text-align:left}
  .field textarea,.field input,textarea{text-align:left!important}
  .gsearch{position:relative;flex:1;max-width:680px;min-width:280px}
  .gsearch input{width:100%;padding:8px 13px;border:1px solid rgba(255,255,255,.25);border-radius:10px;
    background:rgba(255,255,255,.10);color:#fff;font-size:12.5px}
  .gsearch input::placeholder{color:rgba(255,255,255,.55)}
  .gs-results{position:absolute;top:40px;left:0;right:0;background:var(--paper);border:1px solid var(--line);
    border-radius:12px;box-shadow:0 14px 40px rgba(15,30,25,.22);max-height:420px;overflow:auto;z-index:60}
  .gs-row{display:flex;gap:10px;align-items:center;padding:9px 13px;cursor:pointer;border-bottom:1px solid var(--soft)}
  .gs-row:hover{background:var(--soft)} .gs-row .gk{font-size:10px;font-family:var(--f-data);
    letter-spacing:.08em;text-transform:uppercase;color:#fff;border-radius:5px;padding:2px 7px;flex:none}
  .gs-row .gt{font-weight:600;font-size:13px;color:var(--ink)} .gs-row .gsub{font-size:11px;color:var(--mute)}
  .reclink{color:var(--green);font-weight:600;cursor:pointer;text-decoration:none;border-bottom:1px dotted var(--green)}
  .reclink:hover{color:var(--gold);border-color:var(--gold)}
  .demo-cap{position:fixed;left:50%;transform:translateX(-50%);bottom:26px;z-index:120;background:var(--ink);
    color:#fff;padding:14px 22px;border-radius:14px;max-width:680px;box-shadow:0 18px 50px rgba(0,0,0,.35);
    border:1px solid rgba(184,134,43,.5)}
  .demo-cap .dc-t{font-family:var(--f-display);font-size:16px;color:var(--ember);margin-bottom:3px}
  .demo-cap .dc-b{font-size:12.5px;line-height:1.5;opacity:.94}
  .demo-cap .dc-x{position:absolute;top:6px;right:10px;cursor:pointer;opacity:.7}
  label{display:block;font-size:12px;font-weight:600;color:var(--mut);margin-bottom:5px;letter-spacing:.02em}
  input,select,textarea{width:100%;padding:9px 11px;border:1px solid var(--line-strong);border-radius:var(--r-sm);
        font-family:inherit;font-size:13px;background:var(--paper);color:var(--ink);
        transition:border-color var(--dur-1) var(--ease),box-shadow var(--dur-1) var(--ease),
                   background var(--dur-2) var(--ease),color var(--dur-2) var(--ease)}
  /* file inputs are UA-styled and ignore the theme unless told otherwise */
  input[type=file]{padding:7px 9px;color:var(--ink-2)}
  input[type=file]::file-selector-button{font-family:var(--f-ui);font-size:var(--t-xs);font-weight:600;
    background:var(--softer);color:var(--ink-2);border:1px solid var(--line-strong);
    border-radius:var(--r-xs);padding:5px 11px;margin-right:11px;cursor:pointer;
    transition:background var(--dur-1) var(--ease)}
  input[type=file]::file-selector-button:hover{background:var(--sunken);color:var(--ink)}
  input:focus,select:focus,textarea:focus{outline:none;border-color:var(--green);
        box-shadow:0 0 0 3px rgba(26,77,60,.12)}

  /* modal */
  .ovl{position:fixed;inset:0;background:rgba(20,40,32,.42);display:flex;align-items:center;
       justify-content:center;z-index:50;padding:20px;backdrop-filter:blur(3px);
       animation:ovlIn .18s ease}
  .ovl.ovl-full{padding:0}
  .reg-chips{display:flex;flex-wrap:wrap;gap:7px}
  .reg-chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:5px 10px;border-radius:999px;
    border:1px solid var(--line);background:var(--paper);cursor:pointer;user-select:none}
  .reg-chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
  .reg-chip.on .muted{color:#9DBBA8}
  .reg-table{border-collapse:collapse;width:100%;font-size:11.5px}
  .reg-table th,.reg-table td{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
  .reg-table th{background:#F1ECDD;font-weight:600;color:var(--accent);position:sticky;top:0}
  .reg-table .reg-attr{background:#FAF6EC;font-weight:600;color:var(--ink);min-width:150px}
  .reg-new{background:var(--crit);color:#fff;font-size:8.5px;font-weight:700;padding:1px 5px;border-radius:4px;vertical-align:middle}
  @keyframes ovlIn{from{opacity:0}to{opacity:1}}
  .modal{background:var(--paper);border-radius:15px;padding:24px;width:480px;max-width:100%;max-height:90vh;
         overflow:auto;box-shadow:0 30px 80px rgba(0,0,0,.28);
         animation:modalIn .24s cubic-bezier(.16,.84,.44,1)}
  @keyframes modalIn{from{opacity:0;transform:translateY(16px) scale(.98)}to{opacity:1;transform:none}}
  .modal h3{font-size:18px;margin-bottom:16px}
  .modal .row{display:flex;gap:10px;justify-content:flex-end;margin-top:18px}
  .modal.full{width:100vw;height:100vh;max-width:100vw;max-height:100vh;border-radius:0;
         padding:24px 30px;overflow:hidden;display:flex;flex-direction:column;animation:modalFullIn .22s cubic-bezier(.16,.84,.44,1)}
  @keyframes modalFullIn{from{opacity:0;transform:scale(.99)}to{opacity:1;transform:none}}
  .modal.full .full-body{flex:1;overflow:auto;max-width:1060px;width:100%;margin:0 auto;padding-right:4px}

  /* login */
  #login{display:flex;align-items:center;justify-content:center;min-height:100vh;width:100%;
         background:radial-gradient(circle at 30% 20%,#15302a,#0B0E0C 70%)}
  #login .box{background:var(--paper);border-radius:var(--r-xl);padding:40px;width:392px;box-shadow:0 30px 80px rgba(0,0,0,.4)}
  #login .brand{text-align:center;margin-bottom:24px}
  #login .brand .logo{width:54px;height:54px;border-radius:14px;margin:0 auto 14px;
        background:linear-gradient(150deg,#E2BD86,var(--ember) 58%,#A87E45);color:#0B0E0C;
        font-family:var(--f-display);font-weight:700;font-size:30px;display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 10px rgba(201,155,95,.4),inset 0 1px 0 rgba(255,255,255,.4)}
  #login .brand b{font-family:var(--f-display);font-size:24px;font-weight:600;color:var(--ink);display:block}
  #login .brand span{font-size:9.5px;letter-spacing:.14em;color:var(--mute);font-family:var(--f-data)}
  #login .tag{font-style:italic;color:var(--mute);font-size:12px;margin-top:8px;text-align:center;display:block}
  /* SSO block */
  .or-div{display:flex;align-items:center;gap:12px;margin:20px 0 16px;color:var(--mute);
          font-size:11px;letter-spacing:.14em;font-family:var(--f-data)}
  .or-div::before,.or-div::after{content:"";flex:1;height:1px;background:var(--line)}
  .sso-list{display:flex;flex-direction:column;gap:10px}
  .sso-btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;
           padding:11px 16px;border:1px solid var(--line);border-radius:12px;background:var(--paper);
           color:var(--ink);font-size:14px;font-weight:500;cursor:pointer;
           transition:border-color var(--dur) var(--ease),background var(--dur) var(--ease),box-shadow var(--dur) var(--ease),transform var(--dur) var(--ease)}
  .sso-btn:hover{border-color:var(--accent);background:var(--soft);box-shadow:0 3px 12px rgba(20,48,42,.10)}
  .sso-btn:active{transform:translateY(1px)}
  .sso-btn .ico{width:18px;height:18px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
  .sso-btn .ico svg{width:18px;height:18px;display:block}
  .sso-note{font-size:12px;color:var(--mute);text-align:center;margin-top:12px;min-height:1em}
  .sso-note.warn{color:var(--warn)}
  .err{background:#f7e6e3;color:var(--crit);padding:9px 12px;border-radius:var(--r-sm);font-size:12px;margin-bottom:12px}
  .muted{color:var(--mute);font-size:12.5px}
  .flash{position:fixed;bottom:20px;right:20px;background:var(--accent);color:#fff;padding:12px 18px;
         border-radius:var(--r-sm);font-size:13px;box-shadow:var(--sh-3);z-index:60}

  /* ---- AI Assessment chat surface ---- */
  .chat-wrap{display:grid;grid-template-columns:200px 1fr 230px;gap:14px;height:calc(100vh - 150px)}
  .chat-rail{background:var(--paper);border:1px solid var(--line);border-radius:11px;padding:14px;overflow:auto}
  .chat-rail h4{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);margin-bottom:8px}
  .agent-row{display:flex;align-items:center;gap:8px;padding:5px 4px;border-radius:7px;font-size:12px}
  .agent-row.active{background:#f0ede3}
  .adot{width:26px;height:26px;border-radius:50%;color:#fff;display:flex;align-items:center;
        justify-content:center;font-weight:800;font-size:11px;flex-shrink:0}
  .agent-row .an{font-weight:600} .agent-row .at{color:var(--mut);font-size:10px}
  .stagestrip{display:flex;gap:3px;margin-bottom:10px;flex-wrap:wrap}
  .ststep{flex:1;min-width:54px;text-align:center;padding:5px 2px;border-radius:5px;font-size:9px;
          font-weight:700;letter-spacing:.04em;background:#efece2;color:var(--mut)}
  .ststep.cur{background:var(--green);color:#fff} .ststep.done{background:#dCeadF;color:var(--moss)}
  .chat-main{display:flex;flex-direction:column;background:var(--paper);border:1px solid var(--line);border-radius:11px;overflow:hidden}
  .chat-scroll{flex:1;overflow:auto;padding:16px}
  .cmsg{margin-bottom:14px;display:flex;gap:9px}
  .cmsg.user{justify-content:flex-end}
  .cbub{max-width:78%;padding:9px 13px;border-radius:11px;font-size:13px;line-height:1.5}
  .cbub.agent{background:#f7f5ef;border:1px solid var(--line)}
  .cbub.user{background:var(--green);color:#fff}
  .cbub.sys{background:#f3eee0;color:var(--mut);font-size:11.5px;font-style:italic;max-width:100%;text-align:center;margin:0 auto}
  .cmsg-hdr{font-size:10px;font-weight:700;margin-bottom:3px}
  .chat-input{border-top:1px solid var(--line);padding:11px;display:flex;gap:8px;align-items:flex-end}
  .chat-input textarea{flex:1;border:1px solid var(--line);border-radius:8px;padding:9px;font-family:inherit;font-size:13px;resize:none}
  .insight{border-radius:7px;padding:8px 10px;margin-bottom:7px;font-size:11.5px;border-left:3px solid}
  .insight.high{background:#f6e2de;border-color:var(--rust)}
  .insight.medium{background:#f6ebda;border-color:var(--amber)}
  .insight.low{background:#eef2e8;border-color:var(--moss)}
  .insight .ik{font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
  .learn{background:#f7f5ef;border:1px solid var(--line);border-radius:7px;padding:8px 10px;margin-bottom:7px;font-size:11.5px}
  .dossier-row{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;padding:3px 0;border-bottom:1px solid #eee7d8}
  .dossier-row .dk{color:var(--mut)} .dossier-row .dv{font-weight:600;text-align:right}
  /* ---- supply-chain drill-down drawer ---- */
  .conc-drawer{position:fixed;top:0;right:0;height:100vh;width:420px;max-width:92vw;background:var(--paper);
    box-shadow:-8px 0 32px rgba(20,48,42,.18);border-left:1px solid var(--line);z-index:9000;
    transform:translateX(105%);transition:transform .26s cubic-bezier(.4,0,.2,1);display:flex;flex-direction:column}
  .conc-drawer.open{transform:translateX(0)}
  .conc-drawer .cd-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;
    padding:18px 20px;background:linear-gradient(135deg,var(--ink),var(--accent));color:#f3efe3}
  .conc-drawer .cd-kicker{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:#bcae8a;font-weight:700}
  .conc-drawer .cd-head h3{margin:3px 0 0;font-size:18px;color:#fff;line-height:1.2}
  .conc-drawer .cd-x{background:rgba(255,255,255,.14);border:none;color:#fff;width:30px;height:30px;
    border-radius:8px;cursor:pointer;font-size:14px;flex:none}
  .conc-drawer .cd-x:hover{background:rgba(255,255,255,.28)}
  .conc-drawer .cd-body{padding:16px 20px;overflow-y:auto;flex:1}
  .cd-stats{display:flex;flex-wrap:wrap;gap:14px;padding-bottom:14px;margin-bottom:12px;border-bottom:1px solid var(--line)}
  .cd-stats .cv{font-size:22px;font-weight:700;color:var(--accent);font-family:var(--f-display)}
  .cd-stats .cl{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
  .cd-lab{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--moss);margin:4px 0 8px}
  .cd-card{background:#f7f5ef;border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-bottom:14px}
  .cd-row{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;padding:3px 0}
  .cd-row span{color:var(--mut)} .cd-row b{text-align:right}
  .cd-list{display:flex;flex-direction:column;gap:6px}
  .cd-item{display:flex;flex-direction:column;gap:2px;padding:9px 11px;border:1px solid var(--line);
    border-radius:8px;cursor:pointer;background:var(--paper);transition:border-color .15s,background .15s}
  .cd-item:hover{border-color:var(--moss);background:#f3f6f1}
  .cd-item .ci-name{font-size:13px;font-weight:600;color:var(--ink)}
  .cd-item .ci-meta{font-size:11px;color:var(--mut)}
  .band{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700}
  .band.HIGH{background:#f8d7d7;color:#a02929}.band.ELEVATED{background:#f6e2c8;color:#9a6418}
  .band.MODERATE{background:#e6eef6;color:#2a5a8a}.band.LOW{background:#e3efe6;color:var(--accent)}
  .tag.crit{background:#f8d7d7;color:#a02929;padding:1px 6px;border-radius:4px;font-weight:700}
  /* ---- board intelligence ---- */
  .intel-shell{display:grid;grid-template-columns:340px 1fr;gap:16px;margin-top:6px}
  @media(max-width:1024px){.intel-shell{grid-template-columns:1fr}}
  .intel-console{background:#0e1f1a;color:#bfe3c9;border-radius:12px;padding:14px 16px;height:560px;overflow-y:auto;
    font-family:var(--f-data);font-size:12px;line-height:1.55;box-shadow:inset 0 0 0 1px #1c3a30}
  .intel-console .il-line{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04)}
  .intel-console .il-line b{color:#fff}
  .intel-console .il-line.muted{color:#7f9a86}
  .intel-console .il-line.ok{color:#7fe0a0;font-weight:600}
  .intel-console .il-line.err{color:#ff9b8a}
  .intel-canvas{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:20px 22px;min-height:560px;
    max-height:760px;overflow-y:auto;box-shadow:var(--sh,0 1px 2px rgba(0,0,0,.05))}
  .intel-empty{height:480px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#5a6b62}
  .ie-mark{font-size:46px;color:#cdbd92;margin-bottom:10px}
  .ie-mark.spin{animation:spin 1.6s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .ib-brief{background:linear-gradient(135deg,var(--ink),var(--accent));color:#eef2ec;border-radius:12px;padding:18px 20px}
  .ib-kicker{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:#bcae8a;font-weight:700}
  .ib-brief p{font-size:15px;line-height:1.5;margin:8px 0 14px;color:#f3f6f2}
  .ib-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  @media(max-width:560px){.ib-metrics{grid-template-columns:repeat(2,1fr)}}
  .ib-metrics .ibm-v{font-family:var(--f-display);font-size:21px;font-weight:600;color:#fff}
  .ib-metrics .ibm-k{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:#a9c1ad}
  .bar-row{display:grid;grid-template-columns:120px 1fr 64px;align-items:center;gap:10px;padding:4px 0;font-size:12px}
  .bar-lab{color:var(--mut);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar-track{background:#eef0ea;border-radius:6px;height:14px;overflow:hidden}
  .bar-fill{height:100%;border-radius:6px;transition:width .5s ease}
  .bar-val{font-weight:600;font-size:12px}
  .ic-card{background:#fbfaf6;border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .ic-title{font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--moss);margin-bottom:8px}
  .ic-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:720px){.ic-grid{grid-template-columns:1fr}}
  .pestle-row{display:grid;grid-template-columns:120px 1fr 96px;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #efece1}
  .pestle-row:last-child{border-bottom:none}
  .pe-fac{font-weight:700;font-size:13px} .pe-sev{font-size:12px;font-weight:700;text-align:right}
  .pe-head{grid-column:1 / -1;font-size:11.5px;margin-top:-2px}
  .obs-list{display:flex;flex-direction:column;gap:12px}
  .obs-card{background:var(--paper);border:1px solid var(--line);border-left:4px solid #2E6A4F;border-radius:10px;padding:14px 16px}
  .obs-top{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}
  .obs-sev{color:#fff;font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:5px}
  .obs-fac{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border:1px solid;border-radius:5px}
  .obs-hz{font-size:11px;margin-left:auto}
  .obs-card h3{font-size:16px;margin:2px 0 8px;color:var(--ink)}
  .obs-ev,.obs-sw{font-size:12.5px;color:var(--ink-soft,#4a554f);margin-bottom:6px;line-height:1.5}
  .obs-ev b,.obs-sw b{color:var(--moss)}
  .obs-act{font-size:13px;background:#f3f6f1;border:1px solid #d8e6dc;border-radius:8px;padding:9px 11px;margin-top:6px;line-height:1.5}
  .oa-tag{display:inline-block;background:var(--accent);color:#fff;font-size:9.5px;font-weight:700;letter-spacing:.05em;
    text-transform:uppercase;padding:2px 7px;border-radius:5px;margin-right:7px}
  .pred-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
  @media(max-width:720px){.pred-grid{grid-template-columns:1fr}}
  .pred-card{background:#fbfaf6;border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .pred-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
  .pred-metric{font-family:var(--f-display);font-size:18px;font-weight:600;color:var(--accent)}
  .pred-conf{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--gold,var(--ember))}
  .pred-card h4{font-size:14px;margin:2px 0 5px;color:var(--ink)}
  .pred-card p{font-size:12px;line-height:1.5;margin:0}
  /* ---- home tile launcher ---- */
  .home-hero{max-width:920px;margin:0 auto;padding:36px 16px 60px;text-align:center}
  .home-mark{margin-bottom:30px}
  .home-logo{width:64px;height:64px;border-radius:18px;margin:0 auto 16px;
    background:linear-gradient(145deg,var(--ember),#9c6f23);display:flex;align-items:center;justify-content:center;
    font-family:var(--f-display);font-weight:600;font-size:34px;color:var(--ink);box-shadow:0 8px 22px rgba(20,48,42,.22)}
  .home-word{font-family:var(--f-display);font-weight:500;font-size:40px;color:var(--accent);letter-spacing:-.02em}
  .home-word span{color:var(--gold,var(--ember));font-weight:400}
  .home-tag{font-size:16px;color:var(--mut,#5a6b62);margin-top:8px}
  .home-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-top:8px}
  .home-tile{display:flex;align-items:center;gap:14px;text-align:left;background:var(--paper);border:1px solid var(--line,#e1dcce);
    border-radius:14px;padding:16px 16px;cursor:pointer;box-shadow:0 1px 2px rgba(20,48,42,.05);
    transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease;position:relative;overflow:hidden}
  .home-tile::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--ac,var(--accent));opacity:.85}
  .home-tile:hover{transform:translateY(-3px);box-shadow:0 6px 16px rgba(20,48,42,.12),0 16px 36px rgba(20,48,42,.1);border-color:var(--ac,var(--accent))}
  .ht-ico{flex:none;width:42px;height:42px;border-radius:11px;display:flex;align-items:center;justify-content:center;
    font-size:20px;color:#fff}
  .ht-body{display:flex;flex-direction:column;min-width:0;flex:1}
  .ht-title{font-weight:600;font-size:14.5px;color:var(--ink,#15211c);line-height:1.25}
  .ht-sub{font-size:12px;color:var(--mut,#5a6b62);margin-top:2px;line-height:1.35}
  .ht-arrow{flex:none;color:var(--ac,var(--accent));font-size:16px;opacity:0;transform:translateX(-4px);transition:opacity .16s,transform .16s}
  .home-tile:hover .ht-arrow{opacity:1;transform:translateX(0)}
  .home-foot{margin-top:30px;font-size:12px;color:var(--mut,#5a6b62);letter-spacing:.02em}
  /* ---- ProAssess assessment animation ---- */
  .pa-anim{margin-top:16px;background:#0f1714;border-radius:16px;padding:20px 22px;color:#e8efe9;box-shadow:var(--sh)}
  .pa-anim-head{display:flex;align-items:center;gap:14px;margin-bottom:14px}
  .pa-anim-head>div{flex:1}
  .pa-anim-head b{font-family:var(--f-display);font-size:18px;color:#fff}
  .pa-status{font-size:12.5px;color:#9fc4b2;margin-top:2px;font-family:var(--f-data)}
  .pa-pct{font-family:var(--f-display);font-size:26px;color:var(--ember);font-weight:600}
  .pa-spin{width:26px;height:26px;border:3px solid rgba(255,255,255,.15);border-top-color:var(--ember);border-radius:50%;animation:paspin .8s linear infinite;flex:none}
  @keyframes paspin{to{transform:rotate(360deg)}}
  .pa-bar{height:6px;border-radius:6px;background:rgba(255,255,255,.1);overflow:hidden;margin-bottom:18px}
  .pa-bar-fill{height:100%;width:0;border-radius:6px;background:linear-gradient(90deg,var(--accent),var(--ember));transition:width .4s ease}
  .pa-stages{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:18px}
  .pa-stage{display:flex;align-items:center;gap:6px;padding:5px 9px;border-radius:8px;opacity:.45;transition:opacity .3s,background .3s}
  .pa-stage-dot{width:9px;height:9px;border-radius:50%;background:#6b8378;transition:background .3s,box-shadow .3s}
  .pa-stage-name{font-size:11px;font-family:var(--f-data);color:#cfe0d6;white-space:nowrap}
  .pa-stage.on{opacity:1;background:rgba(201,155,95,.14)}
  .pa-stage.on .pa-stage-dot{background:var(--ember);box-shadow:0 0 0 4px rgba(201,155,95,.25);animation:papulse 1s ease-in-out infinite}
  .pa-stage.done{opacity:1}
  .pa-stage.done .pa-stage-dot{background:#3fae7a}
  .pa-stage-sep{width:14px;height:1px;background:rgba(255,255,255,.18)}
  @keyframes papulse{0%,100%{box-shadow:0 0 0 3px rgba(201,155,95,.3)}50%{box-shadow:0 0 0 7px rgba(201,155,95,.08)}}
  .pa-agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:9px}
  .pa-agent{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
    border-radius:11px;padding:9px 11px;opacity:.5;transition:opacity .3s,border-color .3s,background .3s,transform .2s}
  .pa-av{flex:none;width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;
    font-family:var(--f-display);font-weight:600;font-size:15px;color:#fff}
  .pa-ab{display:flex;flex-direction:column;min-width:0;flex:1}
  .pa-an{font-size:13px;font-weight:600;color:#fff;line-height:1.2}
  .pa-ad{font-size:10.5px;color:#8fae9f;line-height:1.3}
  .pa-as{font-size:10px;font-family:var(--f-data);color:#7d9488;white-space:nowrap}
  .pa-agent.active{opacity:1;border-color:var(--ember);background:rgba(201,155,95,.12);transform:translateY(-2px)}
  .pa-agent.active .pa-as{color:var(--ember)}
  .pa-agent.done{opacity:1;border-color:rgba(63,174,122,.4)}
  .pa-agent.done .pa-as{color:#3fae7a}

  /* ===== Performance: SLA Management + Performance Issues ===== */
  .sla-tabs,.pi-toolbar{display:flex;gap:8px;align-items:center;margin:14px 0}
  .sla-tabs{border-bottom:2px solid var(--line);gap:2px}
  .sla-tab{padding:10px 18px;font-size:14px;font-weight:600;color:var(--mute);background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-2px;cursor:pointer;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:8px}
  .sla-tab:hover{color:var(--accent)}
  .sla-tab.active{color:var(--accent);border-bottom-color:var(--accent-2)}
  .tabnum{font-size:11px;background:var(--softer);border:1px solid var(--line);padding:1px 8px;border-radius:20px;color:var(--mute);font-weight:600}
  .tabdot{width:8px;height:8px;border-radius:50%;background:var(--crit);display:none}
  .sla-sources{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px}
  .sla-src{display:flex;flex-direction:column;gap:6px;padding:16px}
  .sla-src p{flex:1;font-size:12px;margin:0}
  .sla-panelh{display:flex;align-items:center;gap:10px;padding:13px 18px;border-bottom:1px solid var(--line)}
  table.reg{width:100%;border-collapse:collapse}
  table.reg thead th{text-align:left;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--mute);font-weight:600;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--soft);white-space:nowrap}
  table.reg tbody td{padding:11px 14px;border-bottom:1px solid var(--line-2);font-size:13px;vertical-align:middle}
  table.reg tbody tr.reg-row:hover{background:var(--soft);cursor:pointer}
  .sdot{display:inline-flex;width:20px;height:20px;border-radius:50%;align-items:center;justify-content:center;font-size:12px;font-weight:700}
  .sdot.ok{background:#E7F5EC;color:var(--ok)}.sdot.bad{background:#FBEAE8;color:var(--crit)}.sdot.none{background:#eee;color:#999}
  .s-ok{color:var(--ok)}.s-bad{color:var(--crit)}.s-none{color:#999}
  .winchip{font-size:11px;font-weight:600;padding:3px 9px;border-radius:6px;background:var(--softer);border:1px solid var(--line);color:var(--accent)}
  .srcb,.srcb2{font-size:9.5px;letter-spacing:.03em;text-transform:uppercase;padding:2px 7px;border-radius:5px;font-weight:700}
  .srcb.contract,.src-sla{background:#FBEAE8;color:var(--crit)}.srcb.upload,.src-ai{background:#F2E9FA;color:#6b21a8}
  .srcb.manual,.src-manual{background:#EAF0F4;color:#3F5566}.src-incident{background:#FBF1DC;color:#8a5a1a}
  .iconb{width:28px;height:28px;border-radius:7px;background:none;border:none;color:var(--mute);font-size:14px;cursor:pointer}
  .iconb:hover{background:var(--softer);color:var(--accent)}
  .nowrap{white-space:nowrap}.mono{font-family:'SF Mono','Consolas',monospace;font-size:12px;color:var(--green-d);font-weight:600}
  .sm{font-size:11.5px}
  .meas-wrap{padding:14px 18px;background:var(--soft)}
  .periods{display:flex;gap:10px;flex-wrap:wrap}
  .per{background:var(--paper);border:1px solid var(--line);border-radius:9px;padding:9px 11px;min-width:120px}
  .per .pk{font-size:11px;font-weight:600;color:var(--mute);margin-bottom:5px}
  .per .pi{display:flex;align-items:center;gap:6px}
  .per input{width:66px;border:1px solid var(--line);border-radius:6px;padding:5px 7px;font-size:13px;text-align:right}
  .per.met{border-color:#bfe3cd;background:#E7F5EC}.per.breach{border-color:#f1c9c3;background:#FBEAE8}
  .per .vd{font-size:10px;font-weight:700;margin-top:5px}.per.met .vd{color:var(--ok)}.per.breach .vd{color:var(--crit)}
  .ai-card .ai-h,.ai-h{display:flex;align-items:center;gap:9px;font-weight:700;color:var(--accent);font-size:14px;padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:12px}
  .ai-badge{margin-left:auto;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:#8a5a1a;border:1px solid #e8c07a;padding:2px 8px;border-radius:20px;font-weight:600}
  .ai-stats{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
  .ai-s{background:var(--soft);border:1px solid var(--line);border-radius:9px;padding:9px 14px;min-width:88px}
  .ai-s .v{font-size:22px;font-weight:700;color:var(--accent);line-height:1}.ai-s.ok .v{color:var(--ok)}.ai-s.bad .v{color:var(--crit)}
  .ai-s .l{font-size:10.5px;color:var(--mute);margin-top:3px}
  .chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
  .chip{font-size:11.5px;background:var(--paper);border:1px solid var(--line);border-radius:20px;padding:5px 12px;color:var(--accent);cursor:pointer}
  .chip:hover{border-color:var(--accent-2);background:#FBF4E4}
  .qa{margin-top:12px}.qa-q{font-size:13px;color:var(--accent);margin-bottom:4px}
  .qa-a{font-size:13px;background:var(--paper);border:1px solid var(--line);border-left:3px solid var(--accent-2);border-radius:8px;padding:10px 13px}
  .sevstrip{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin:14px 0}
  .sevcard{background:var(--paper);border:1px solid var(--line);border-left-width:4px;border-radius:11px;padding:12px 15px;cursor:pointer}
  .sevcard:hover{box-shadow:0 2px 10px rgba(0,0,0,.06)}.sevcard.active{box-shadow:0 0 0 2px var(--accent-2)}
  .sevcard .n{font-size:24px;font-weight:700;line-height:1}.sevcard .l{font-size:11px;color:var(--mute);margin-top:4px;text-transform:uppercase;letter-spacing:.04em;font-weight:600}
  .sevcard.all{border-left-color:var(--accent)}.sevcard.all .n{color:var(--accent)}
  .sevcard.crit{border-left-color:#7A1F2B}.sevcard.crit .n{color:#7A1F2B}
  .sevcard.high{border-left-color:var(--crit)}.sevcard.high .n{color:var(--crit)}
  .sevcard.med{border-left-color:var(--warn)}.sevcard.med .n{color:var(--warn)}
  .sevcard.low{border-left-color:#3F5566}.sevcard.low .n{color:#3F5566}
  .tagp{font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;white-space:nowrap}
  .sev-crit{background:#F7E4E6;color:#7A1F2B}.sev-high{background:#FBE7E3;color:var(--crit)}.sev-med{background:#FBF1DC;color:var(--warn)}.sev-low{background:#EAF0F4;color:#3F5566}
  .st-open{background:#FBE7E3;color:var(--crit)}.st-prog{background:#E7F0F8;color:#2d6ea3}.st-rev{background:#F2E9FA;color:#6b21a8}.st-closed{background:#E7F5EC;color:var(--ok)}.st-acc{background:#FBF1DC;color:#8a5a1a}
  .pi-toolbar select{border:1px solid var(--line);border-radius:8px;padding:8px 11px;background:var(--paper)}
  .btn.gold{background:var(--accent-2);color:#fff}.btn.sm{padding:7px 12px;font-size:12px}
  .pi-det{display:grid;grid-template-columns:1.4fr 1fr;gap:22px;padding:16px 20px;background:var(--soft)}
  .det-b{margin-bottom:14px}.det-b h5{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);margin:0 0 6px}
  .rem-b{background:var(--paper);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:10px 12px;font-size:12.5px}
  .det-acts{display:flex;gap:7px;flex-wrap:wrap}
  .kv{display:flex;gap:10px;font-size:12.5px;padding:4px 0;border-bottom:1px solid var(--line-2)}.kv .muted{min-width:110px}
  .tl{list-style:none;padding:0;margin:0}.tl li{position:relative;padding:0 0 11px 17px;font-size:12px}
  .tl li::before{content:'';position:absolute;left:0;top:5px;width:8px;height:8px;border-radius:50%;background:var(--accent-2)}
  @media(max-width:900px){.sla-sources{grid-template-columns:1fr}.sevstrip{grid-template-columns:repeat(2,1fr)}.pi-det{grid-template-columns:1fr}}

  /* ===== Platform docs (SOP / Technical Details) + Version Control ===== */
  .doc-frame-wrap{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--paper);height:calc(100vh - 180px);min-height:520px}
  .doc-frame{width:100%;height:100%;border:0;display:block;background:var(--paper)}
  .ver-rail{position:relative;padding-left:8px;max-width:880px}
  .ver-card{position:relative;border:1px solid var(--line);border-radius:12px;background:var(--paper);padding:16px 20px;margin:0 0 16px 22px}
  .ver-card::before{content:'';position:absolute;left:-22px;top:20px;width:11px;height:11px;border-radius:50%;background:var(--accent-2);border:2px solid #fff;box-shadow:0 0 0 1px var(--line)}
  .ver-card::after{content:'';position:absolute;left:-17px;top:31px;bottom:-16px;width:1px;background:var(--line)}
  .ver-card:last-child::after{display:none}
  .ver-card.latest{border-color:var(--accent-2);box-shadow:0 2px 14px rgba(201,155,95,.12)}
  .ver-card.latest::before{background:var(--accent);width:13px;height:13px;left:-23px}
  .ver-head{display:flex;align-items:center;gap:10px;margin-bottom:4px}
  .ver-tag{font-family:'SF Mono','Consolas',monospace;font-weight:700;font-size:15px;color:var(--accent)}
  .ver-cur{font-size:9.5px;letter-spacing:.06em;background:var(--accent);color:#fff;padding:2px 8px;border-radius:20px;font-weight:700}
  .ver-date{font-size:12px;color:var(--mute);margin-left:auto}
  .ver-title{font-size:14px;font-weight:600;color:var(--ink);margin-bottom:10px}
  .ver-sec{margin-bottom:9px}
  .ver-sec-h{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--accent-2);font-weight:700;margin-bottom:3px}
  .ver-sec ul{margin:0 0 0 18px;padding:0}
  .ver-sec li{font-size:12.5px;line-height:1.5;color:var(--ink-2);margin-bottom:3px}
  @media print{aside,.top button,.help-drawer{display:none!important}}

  /* ===== Dashboards ===== */
  .dash-tabs,.sla-tabs{display:flex;gap:2px;border-bottom:2px solid var(--line);margin:14px 0}
  .dash-tab{padding:10px 18px;font-size:13.5px;font-weight:600;color:var(--mute);background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-2px;cursor:pointer;border-radius:8px 8px 0 0}
  .dash-tab:hover{color:var(--accent)}.dash-tab.active{color:var(--accent);border-bottom-color:var(--accent-2)}
  .dkpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
  .dkpi{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .dkpi-v{font-family:Georgia,serif;font-size:30px;font-weight:700;color:var(--accent);line-height:1}
  .dkpi-l{font-size:11.5px;color:var(--mute);margin-top:5px;text-transform:uppercase;letter-spacing:.03em;font-weight:600}
  .dgrid{display:grid;grid-template-columns:1fr 1fr;gap:13px}
  .dcard{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .dcard h4{font-size:13px;font-weight:700;color:var(--accent);margin:0 0 12px}
  .dbar{display:grid;grid-template-columns:120px 1fr 34px;align-items:center;gap:10px;margin-bottom:8px}
  .dbar-l{font-size:12px;color:var(--ink-2);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dbar-track{background:var(--softer);border-radius:20px;height:18px;overflow:hidden}
  .dbar-fill{height:100%;border-radius:20px;min-width:2px;transition:width .4s ease}
  .dbar-v{font-size:12px;font-weight:700;color:var(--accent);text-align:right}
  /* ===== Learnings ===== */
  .learn-filters{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}
  .lchip{font-size:11.5px;background:var(--paper);border:1px solid var(--line);border-radius:20px;padding:5px 13px;color:var(--accent);cursor:pointer}
  .lchip:hover{border-color:var(--accent-2)}.lchip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  .learn-card{background:var(--paper);border:1px solid var(--line);border-radius:11px;padding:14px 16px;margin-bottom:11px}
  .learn-head{display:flex;align-items:center;gap:8px;margin-bottom:7px}
  .lcat{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:3px 9px;border-radius:6px;background:var(--gold-p,#FBF4E4);color:#7a5015}
  .lorigin{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:20px}
  .lorigin.auto{background:#E7F5EC;color:#15603f}.lorigin.human{background:#EAF2F6;color:#1f5066}
  .lconf{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}
  .c-high{background:#FBE7E3;color:#7A1F2B}.c-medium{background:#FBF1DC;color:#8a5a1a}.c-low{background:#EAF0F4;color:#3F5566}
  .lreuse{font-size:11px;color:var(--mute);font-weight:600}
  .learn-insight{font-size:13.5px;line-height:1.55;color:var(--ink)}
  .learn-src{margin-top:6px}
  /* ===== BRO Chat persona highlight + AI banner ===== */
  .ai-banner{border-radius:10px;padding:11px 15px;font-size:12.5px;margin:0 0 12px;line-height:1.5}
  .ai-banner.ok{background:#E7F5EC;border:1px solid #9dcdb8;color:#15603f}
  .ai-banner.warn{background:#FDF6EC;border:1px solid #e8c07a;color:#7a5015}
  .ai-banner a{color:inherit;font-weight:700}
  .agent-row.active{background:linear-gradient(90deg,color-mix(in srgb,var(--apc,var(--ink)) 12%,#fff),#fff);border:1px solid var(--apc,var(--line));box-shadow:0 1px 6px rgba(0,0,0,.06)}
  .agent-row{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:9px;border:1px solid transparent;margin-bottom:4px}
  .speaking{font-size:9.5px;font-weight:700;color:#15603f;background:#E7F5EC;border-radius:20px;padding:2px 8px;animation:pulse 1.6s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
  .adot.persona{width:34px;height:34px;font-size:14px;font-weight:700;flex-shrink:0}
  .persona-hdr{display:flex;align-items:baseline;gap:8px;margin-bottom:4px}
  .persona-name{font-weight:700;font-size:13.5px}
  .persona-title{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.03em}
  .cbub.agent{background:var(--paper);border:1px solid var(--line);border-radius:4px 12px 12px 12px;padding:11px 14px}
  .asr-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--line-2)}
  .asr-row:last-child{border-bottom:none}
  @media(max-width:900px){.dkpis,.dgrid{grid-template-columns:1fr 1fr}}
  /* ===== v4.9 fluid displays & form polish (UX pass) ===== */
  .card{transition:box-shadow .22s ease, transform .22s ease, border-color .22s ease}
  .card:hover{box-shadow:0 10px 28px -14px rgba(20,48,42,.28);border-color:#D8CFBB}
  .btn{transition:transform .14s ease, box-shadow .14s ease, background .14s ease, opacity .14s ease}
  .btn:hover{transform:translateY(-1px)}
  .btn:active{transform:translateY(0) scale(.985)}
  #nav a{transition:background .16s ease, color .16s ease, padding-left .16s ease}
  #view{animation:viewIn .28s ease}
  @keyframes viewIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  input:focus-visible,select:focus-visible,textarea:focus-visible{outline:none;border-color:var(--ember);
    box-shadow:0 0 0 3px rgba(184,134,43,.18);transition:border-color .15s ease, box-shadow .15s ease}
  .field{margin-bottom:10px}
  .field label{display:block;font-size:11px;font-weight:600;color:#5A6472;margin-bottom:4px;letter-spacing:.02em}
  .card .grid{align-items:start}
  table tr{transition:background .14s ease}
  @media (prefers-reduced-motion: reduce){
    .card,.btn,#nav a,#view,table tr,input,select,textarea{transition:none!important;animation:none!important}
  }
  /* streaming chat typing indicator */
  .typing{display:inline-flex;gap:4px;align-items:center;padding:2px 0}
  .typing i{width:6px;height:6px;border-radius:50%;background:var(--ember);opacity:.5;animation:typing 1.1s infinite ease-in-out}
  .typing i:nth-child(2){animation-delay:.18s}
  .typing i:nth-child(3){animation-delay:.36s}
  @keyframes typing{0%,60%,100%{transform:translateY(0);opacity:.45}30%{transform:translateY(-4px);opacity:1}}
  @media (prefers-reduced-motion: reduce){ .typing i{animation:none} }
  /* Fast Track / Deep Research toggle bar */
  .aimode-bar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    background:var(--softer);border:1px solid var(--line);border-radius:var(--r-md);
    padding:8px 12px;margin-bottom:14px}
  .aimode-lbl{font-size:var(--t-micro);font-weight:600;letter-spacing:.12em;text-transform:uppercase;
    color:var(--faint);font-family:var(--f-data)}
  .aimode-seg{display:inline-flex;background:var(--sunken);border:1px solid var(--line);
    border-radius:var(--r-sm);padding:2px}
  .aimode-seg button{appearance:none;border:0;background:transparent;font-size:var(--t-sm);font-weight:600;
    color:var(--mute);padding:5px 12px;border-radius:var(--r-xs);cursor:pointer;width:auto;
    transition:background var(--dur-1) var(--ease),color var(--dur-1) var(--ease)}
  .aimode-seg button:hover{color:var(--ink)}
  .aimode-seg button.on{background:var(--accent);color:var(--accent-ink);box-shadow:var(--sh-1)}
  .aimode-note{max-width:34ch;font-size:var(--t-xs);color:var(--mute);flex:1;min-width:180px}
  @media (prefers-reduced-motion: reduce){ .aimode-seg button{transition:none} }
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login">
  <div class="box">
    <div class="brand"><div class="logo">B</div><b>Brata</b><span>ENTERPRISE TPRM</span>
      <span class="tag">Exposure first. Controls second. Verdict last.</span></div>
    <div id="loginErr" class="err hidden"></div>
    <div class="field"><label>Sign in as</label>
      <select id="loginRole" onchange="pickRole()" style="width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--paper)">
        <option value="">— Developer (admin/admin) —</option>
        <option value="admin">Administrator</option>
        <option value="buyer">Buyer / Business Lead</option>
        <option value="vrm">Assessor</option>
        <option value="controller">Controller</option>
        <option value="exec">Executive Management</option>
        <option value="vendor">Supplier (self-service)</option>
      </select></div>
    <div class="field"><label>Username</label><input id="lu" value="admin"></div>
    <div class="field"><label>Password</label><input id="lp" onkeydown="if(event.key==='Enter')doLogin()" type="password" value="admin"></div>
    <button class="btn" style="width:100%" onclick="doLogin()">Sign in</button>

    <div class="or-div">OR</div>
    <div class="sso-list" id="ssoList">
      <button class="sso-btn" id="ssoGoogle" onclick="ssoStart('google')">
        <span class="ico"><svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/>
          <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/>
          <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z"/>
          <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.46 3.44 1.35l2.58-2.58C13.47.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/>
        </svg></span>Continue with Google</button>
      <button class="sso-btn" id="ssoApple" onclick="ssoStart('apple')">
        <span class="ico"><svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path fill="#111" d="M13.03 9.53c-.02-1.9 1.55-2.81 1.62-2.85-.88-1.29-2.26-1.47-2.75-1.49-1.17-.12-2.28.69-2.87.69-.59 0-1.5-.67-2.47-.65-1.27.02-2.44.74-3.09 1.87-1.32 2.29-.34 5.67.94 7.53.63.91 1.37 1.93 2.35 1.9.94-.04 1.3-.61 2.44-.61 1.13 0 1.46.61 2.46.59 1.02-.02 1.66-.92 2.28-1.84.72-1.05 1.02-2.07 1.03-2.12-.02-.01-1.97-.76-1.99-3.01zM11.2 3.9c.52-.63.87-1.5.77-2.37-.75.03-1.65.5-2.19 1.13-.48.55-.9 1.44-.79 2.29.83.06 1.68-.42 2.21-1.05z"/>
        </svg></span>Continue with Apple</button>
      <button class="sso-btn" id="ssoEnterprise" onclick="ssoStart('enterprise')">
        <span class="ico"><svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path fill="var(--accent)" d="M9 1l6 2.4v4.1c0 3.7-2.5 7.1-6 8.1-3.5-1-6-4.4-6-8.1V3.4L9 1z"/>
          <path fill="var(--ember)" d="M9 5.2a1.9 1.9 0 0 0-.8 3.62V11a.8.8 0 0 0 1.6 0V8.82A1.9 1.9 0 0 0 9 5.2z"/>
        </svg></span>Continue with SSO</button>
    </div>
    <div class="sso-note" id="ssoNote"></div>

    <p class="muted" style="text-align:center;margin-top:14px">Pick a role to sign in, or use admin / admin.</p>
  </div>
</div>

<!-- APP -->
<div id="app" class="hidden">
  <header class="topbar">
    <div class="brand">
      <button class="nav-toggle" onclick="toggleNav()" title="Hide / show menu" aria-label="Toggle menu">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
             stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button>
      <div class="logo">B</div>
      <div><div class="brand-name">Brata</div>
        <div class="brand-sub">ENTERPRISE TPRM · POWERED BY CLAUDE</div></div>
    </div>
    <div class="topbar-right">
      <button class="theme-switch" onclick="toggleTheme()" title="Light / dark appearance"
              aria-label="Toggle light or dark appearance">
        <span class="knob">
          <svg class="ico-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.4"/><path d="M12 1.8v2.6M12 19.6v2.6M4.2 4.2l1.9 1.9M17.9 17.9l1.9 1.9M1.8 12h2.6M19.6 12h2.6M4.2 19.8l1.9-1.9M17.9 6.1l1.9-1.9"/></svg>
          <svg class="ico-moon" viewBox="0 0 24 24"><path d="M20 14.2A8.2 8.2 0 1 1 9.8 4a6.6 6.6 0 0 0 10.2 10.2z"/></svg>
        </span></button>
      <button class="help-btn" onclick="openHelp()" title="Explain this page">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
             stroke-linecap="round"><circle cx="12" cy="12" r="9.2"/><path d="M9.2 9.2a2.9 2.9 0 1 1 3.6 2.8v1.6"/><path d="M12 17.2h.01"/></svg>
        Help</button>
      <div class="role-badge" onclick="go('account')" style="cursor:pointer" title="Account management"><span class="role-ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
   stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.8l7.4 3v5.4c0 4.6-3.1 8.4-7.4 10-4.3-1.6-7.4-5.4-7.4-10V5.8z"/></svg></span>
        <div><div class="role-name" id="whoName">—</div><div class="role-kind" id="whoRole">—</div></div></div>
      <div class="gsearch" id="gsWrap">
        <input id="gs" placeholder="Search suppliers, engagements, incidents, pages…" autocomplete="off"
               oninput="gSearch(this.value)" onfocus="gSearch(this.value)" aria-label="Global search">
        <div id="gsResults" class="gs-results" style="display:none"></div>
      </div>
      <button class="signout" style="background:var(--ember);border-color:transparent;color:#1A0E06;font-weight:700"
   onclick="startAutoDemo()" title="Auto slideshow demo">Demo</button>
      <button class="signout" onclick="logout()">Sign out</button>
    </div>
  </header>
  <div class="help-overlay" id="helpOverlay" onclick="closeHelp()"></div>
  <aside class="help-drawer" id="helpDrawer" aria-label="Page help">
    <div class="help-head" style="position:relative">
      <button class="hx" onclick="closeHelp()" aria-label="Close help">✕</button>
      <h3 id="helpTitle">Help</h3><div class="hsub" id="helpSub"></div>
    </div>
    <div class="help-body" id="helpBody"></div>
  </aside>
  <div class="shell">
    <aside>
      <nav id="nav" role="navigation" aria-label="Primary">
        <div class="nav-group">
          <a data-v="home" class="active"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.6 12 3.4l9 7.2M5.4 9.4V20h13.2V9.4M9.8 20v-6h4.4v6"/></svg></span>Home</a>
          <a data-v="methodology" id="navMethodology" style="display:none"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M4 20 20 4M8.6 20v-4.2M13 20v-8.4"/></svg></span>Methodology</a>
          <a data-v="dashboards"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h16M7.4 20V11M12 20V5.6M16.6 20v-5.6"/></svg></span>Dashboards</a>
          <a data-v="learnings"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 4.2a3 3 0 0 0-3 3 3 3 0 0 0-1.6 5.3A3 3 0 0 0 7.2 18a3 3 0 0 0 4.8 1.4V4.9a3 3 0 0 0-2.6-.7zM14.6 4.2a3 3 0 0 1 3 3 3 3 0 0 1 1.6 5.3A3 3 0 0 1 16.8 18a3 3 0 0 1-4.8 1.4"/></svg></span>Learnings</a>
          <a data-v="dashboard"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h16M6.6 15.6l3.6-4 3 2.6 4.4-5.6"/></svg></span>Snapshot</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Assess</div>
          <a data-v="assess"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.6h14a1.6 1.6 0 0 1 1.6 1.6v8.4a1.6 1.6 0 0 1-1.6 1.6H9.6L5.4 20V4.6z"/></svg></span>BRO Chat</a>
          <a data-v="proassess"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.4 2.6 5 13.4h5.4L9.6 21.4 19 10.6h-5.4z"/></svg></span>ProAssess</a>
          <a data-v="genie"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2c2.4 0 4 1.8 4 4.2 0 2-1.2 3-2.2 3.8-.8.6-1.2 1-1.2 2M12 17.8h.01M6 20.4h12"/></svg></span>TPRM Genie</a>
          <a data-v="brocall"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.4h3l1.4 3.6-2 1.4a11 11 0 0 0 5.2 5.2l1.4-2 3.6 1.4v3a1.6 1.6 0 0 1-1.8 1.6C11.4 18.2 5.8 12.6 5.4 6.2A1.6 1.6 0 0 1 7 4.4z"/></svg></span>BroCall</a>
          <a data-v="assessments"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 7.4a1.6 1.6 0 0 1 1.6-1.6h4l2 2.4h7.4a1.6 1.6 0 0 1 1.6 1.6v8.4a1.6 1.6 0 0 1-1.6 1.6H5a1.6 1.6 0 0 1-1.6-1.6z"/></svg></span>Assessments</a>
          <a data-v="engagements"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.6 3.6h16.8v16.8H3.6zM3.6 9.2h16.8M3.6 14.8h16.8M9.2 3.6v16.8M14.8 3.6v16.8"/></svg></span>Engagements</a>
          <a data-v="vendors"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.4 20.4V5a1.6 1.6 0 0 1 1.6-1.6h7.2A1.6 1.6 0 0 1 14.8 5v15.4M14.8 10h3.6a1.6 1.6 0 0 1 1.6 1.6v8.8M3 20.4h18M8 7.6h3M8 11.4h3M8 15.2h3"/></svg></span>Supplier Register</a>
          <a data-v="artefacts"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.4h9.6L19 6.8v13.8H6zM15.2 3.4v3.8H19M9 11.6h7M9 15.2h7"/></svg></span>Certifications</a>
          <a data-v="fdd"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4v17.2M15.8 7.2c0-1.4-1.7-2.4-3.8-2.4S8.2 5.8 8.2 7.4s1.7 2.2 3.8 2.6 3.8 1 3.8 2.6-1.7 2.4-3.8 2.4-3.8-1-3.8-2.4"/></svg></span>Financial DD</a>
          <a data-v="reputation"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.6 5.6h13.2v13.6H5.2a1.6 1.6 0 0 1-1.6-1.6zM16.8 9h2.2a1.4 1.4 0 0 1 1.4 1.4v7.2a1.6 1.6 0 0 1-1.6 1.6h-2M6.4 9h7.6M6.4 12.4h7.6M6.4 15.8h4.6"/></svg></span>Reputation</a>
          <a data-v="oss"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.6 7.6 12 3.4l8.4 4.2v8.8L12 20.6l-8.4-4.2zM3.6 7.6 12 11.8m0 0 8.4-4.2M12 11.8v8.8"/></svg></span>Open Source (SBOM)</a>
          <a data-v="review"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4.2a6.8 6.8 0 1 1 0 13.6 6.8 6.8 0 0 1 0-13.6M16.2 16.2 20.4 20.4"/></svg></span>Review Queue</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Monitor &amp; Manage</div>
          <a data-v="vendor360"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4a8.6 8.6 0 1 1 0 17.2 8.6 8.6 0 0 1 0-17.2M12 8.2a3.8 3.8 0 1 1 0 7.6 3.8 3.8 0 0 1 0-7.6"/></svg></span>Supplier 360</a>
          <a data-v="documents"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 7.4a1.6 1.6 0 0 1 1.6-1.6h4l2 2.4h7.4a1.6 1.6 0 0 1 1.6 1.6v8.4a1.6 1.6 0 0 1-1.6 1.6H5a1.6 1.6 0 0 1-1.6-1.6z"/></svg></span>Documents</a>
          <a data-v="performance"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h16M6.6 15.6l3.6-4 3 2.6 4.4-5.6"/></svg></span>Performance</a>
          <a data-v="slamgmt"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4.6h6a1 1 0 0 1 1 1v1H8v-1a1 1 0 0 1 1-1zM8 6.6H6.4a1.6 1.6 0 0 0-1.6 1.6v10.6a1.6 1.6 0 0 0 1.6 1.6h11.2a1.6 1.6 0 0 0 1.6-1.6V8.2a1.6 1.6 0 0 0-1.6-1.6H16M8.6 11.6h6.8M8.6 15.2h4.6"/></svg></span>SLA Management</a>
          <a data-v="perfissues"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 21 19.4H3zM12 10v4.2M12 17h.01"/></svg></span>Performance Issues</a>
          <a data-v="findings"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.8 12.6 9.4 17.2 19.2 6.8"/></svg></span>Findings</a>
          <a data-v="issues"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 21 19.4H3zM12 10v4.2M12 17h.01"/></svg></span>Issues Log</a>
          <a data-v="incidents"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 19.4v-6.6a5.6 5.6 0 0 1 11.2 0v6.6zM4 19.4h16M12 3.4v2.2"/></svg></span>Supplier Incidents</a>
          <a data-v="watchlist"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.6 12S5.8 6.4 12 6.4 21.4 12 21.4 12 18.2 17.6 12 17.6 2.6 12 2.6 12M12 9.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2"/></svg></span>Watchlist</a>
          <a data-v="remediation"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.2 6.4a3.6 3.6 0 0 1 4.8 4.6l-8.6 8.6-3.2-3.2 8.6-8.6zM6.6 4.4l2.8 2.8-2 2-2.8-2.8z"/></svg></span>Remediation Plans</a>
          <a data-v="fourthparties"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13.6a3.6 3.6 0 0 0 5.4.4l2.6-2.6a3.6 3.6 0 0 0-5-5l-1.5 1.5M14 10.4a3.6 3.6 0 0 0-5.4-.4L6 12.6a3.6 3.6 0 0 0 5 5l1.5-1.5"/></svg></span>4th Party Register</a>
          <a data-v="contracts"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M6 20h12M12 6.6 5.4 9M12 6.6 18.6 9M5.4 9 3 14.4h4.8zM18.6 9 16.2 14.4H21z"/></svg></span>Contracts</a>
          <a data-v="exit"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.6h9.6v16.8H6zM13 12h.01M18 20.4V3.6"/></svg></span>Exit Planning</a>
          <a data-v="notifications"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.6 15.6H6.4l1.2-2v-3.8a4.4 4.4 0 0 1 8.8 0V13.6zM10.4 18.6a1.8 1.8 0 0 0 3.2 0"/></svg></span>Notifications</a>
          <a data-v="schedules"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5.8h14a1.4 1.4 0 0 1 1.4 1.4v12A1.4 1.4 0 0 1 19 20.6H5a1.4 1.4 0 0 1-1.4-1.4v-12A1.4 1.4 0 0 1 5 5.8zM3.6 10.4h16.8M8.4 3.4v4.4M15.6 3.4v4.4"/></svg></span>Schedules</a>
          <a data-v="connections"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4.4v5M15 4.4v5M6.6 9.4h10.8v3a5.4 5.4 0 0 1-5.4 5.4 5.4 5.4 0 0 1-5.4-5.4zM12 17.8v3"/></svg></span>Connections</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Analyse</div>
          <a data-v="pestle"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6v3M12 17.4v3M3.6 12h3M17.4 12h3M12 8.4a3.6 3.6 0 1 1 0 7.2 3.6 3.6 0 0 1 0-7.2M6.2 6.2l2.2 2.2M15.6 15.6l2.2 2.2M17.8 6.2l-2.2 2.2M8.4 15.6l-2.2 2.2"/></svg></span>PESTLE Intelligence</a>
          <a data-v="intel"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4l2.2 6.4 6.4 2.2-6.4 2.2L12 20.6l-2.2-6.4L3.4 12l6.4-2.2z"/></svg></span>Intelligence</a>
          <a data-v="advanced"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 4.2a3 3 0 0 0-3 3 3 3 0 0 0-1.6 5.3A3 3 0 0 0 7.2 18a3 3 0 0 0 4.8 1.4V4.9a3 3 0 0 0-2.6-.7zM14.6 4.2a3 3 0 0 1 3 3 3 3 0 0 1 1.6 5.3A3 3 0 0 1 16.8 18a3 3 0 0 1-4.8 1.4"/></svg></span>Overview</a>
          <a data-v="integrity"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.6v5a4 4 0 0 0 8 0v-5M10 16.6a4.6 4.6 0 0 0 9.2 0v-2M19.2 10.4a2 2 0 1 1 0 4 2 2 0 0 1 0-4M6 3.6H4.4M14 3.6h1.6"/></svg></span>Data Integrity</a>
          <a data-v="entitygraph"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4v17.2M3.6 12h16.8M5.8 5.8l12.4 12.4M18.2 5.8 5.8 18.2M12 7.6a4.4 4.4 0 1 1 0 8.8 4.4 4.4 0 0 1 0-8.8"/></svg></span>Entity Graph</a>
          <a data-v="exposure"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6a8.4 8.4 0 1 1 0 16.8 8.4 8.4 0 0 1 0-16.8M12 7.8a4.2 4.2 0 1 1 0 8.4 4.2 4.2 0 0 1 0-8.4M12 11.4a.6.6 0 1 1 0 1.2.6.6 0 0 1 0-1.2"/></svg></span>BU Exposure</a>
          <a data-v="geopolitical"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4a8.6 8.6 0 1 1 0 17.2 8.6 8.6 0 0 1 0-17.2M3.4 12h17.2M12 3.4a13 13 0 0 1 0 17.2 13 13 0 0 1 0-17.2"/></svg></span>Geopolitical</a>
          <a data-v="criticality"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4l2.7 5.5 6 .9-4.4 4.2 1 6-5.3-2.8-5.3 2.8 1-6L3.3 9.8l6-.9z"/></svg></span>Critical Supplier Modelling</a>
          <a data-v="scenario"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6a8.4 8.4 0 1 1 0 16.8 8.4 8.4 0 0 1 0-16.8M12 7.8a4.2 4.2 0 1 1 0 8.4 4.2 4.2 0 0 1 0-8.4M12 11.4a.6.6 0 1 1 0 1.2.6.6 0 0 1 0-1.2"/></svg></span>Scenario Simulator</a>
          <a data-v="stressradar"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.6 18.4 12 8.6l6.4 9.8M8.4 6.2a5 5 0 0 1 7.2 0M6.2 3.6a8.6 8.6 0 0 1 11.6 0"/></svg></span>Stress Radar</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Understand</div>
          <a data-v="copilot"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4.2a6.8 6.8 0 1 1 0 13.6 6.8 6.8 0 0 1 0-13.6M16.2 16.2 20.4 20.4"/></svg></span>Ask Anything</a>
          <a data-v="management"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h16M7.4 20V11M12 20V5.6M16.6 20v-5.6"/></svg></span>Management</a>
          <a data-v="globalreg"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4a8.6 8.6 0 1 1 0 17.2 8.6 8.6 0 0 1 0-17.2M3.4 12h17.2M12 3.4a13 13 0 0 1 0 17.2 13 13 0 0 1 0-17.2"/></svg></span>Global Regulations</a>
          <a data-v="boardpack"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.4h12v17.2l-6-3.4-6 3.4zM9 8h6"/></svg></span>Board / Regulator Pack</a>
          <a data-v="reports"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.6 6.6a1.6 1.6 0 0 1 1.6-1.6h4l2 2.4h7a1.6 1.6 0 0 1 1.6 1.6v8.4a1.6 1.6 0 0 1-1.6 1.6H5.2a1.6 1.6 0 0 1-1.6-1.6z"/></svg></span>Reports</a>
          <a data-v="aireports"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8.4h8a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2zM12 5v3.4M9.4 12.4h.01M14.6 12.4h.01M9.8 16h4.4M3.6 12.6v2.4M20.4 12.6v2.4"/></svg></span>AI Reports</a>
          <a data-v="evidence"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l7.4 3v5.4c0 4.6-3.1 8.4-7.4 10-4.3-1.6-7.4-5.4-7.4-10V5.8z"/></svg></span>Evidence on Demand</a>
          <a data-v="lifecycle"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.6 7.4 5 12l2.2 3.8h4M16.4 16.6 19 12l-2.2-3.8h-4M9.4 19.4 12 15.6M14.6 4.6 12 8.4"/></svg></span>Lifecycle</a>
          <a data-v="governance"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.6 7.4c0-1.7-1.2-2.8-2.8-2.8s-2.8 1.1-2.8 2.6c0 3.2 5.6 2.4 5.6 5.6 0 1.5-1.2 2.6-2.8 2.6s-2.8-1.1-2.8-2.8M14.6 12.4c0 1.7-1.2 2.8-2.8 2.8S9 16.3 9 17.8c0 1.5 1.2 2.6 2.8 2.6"/></svg></span>Governance</a>
          <a data-v="audit"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 10.4h11.2a1.4 1.4 0 0 1 1.4 1.4v7a1.4 1.4 0 0 1-1.4 1.4H6.4A1.4 1.4 0 0 1 5 18.8v-7a1.4 1.4 0 0 1 1.4-1.4zM8.4 10.4V7.8a3.6 3.6 0 0 1 7.2 0v2.6"/></svg></span>Audit Trail</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Documentation</div>
          <a data-v="sop"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.6h9.6a2.4 2.4 0 0 1 2.4 2.4v12.4H7.4A2.4 2.4 0 0 1 5 17V4.6zM19 6.6v12.8"/></svg></span>SOP</a>
          <a data-v="techdetails"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 4.4h5.2v2.4a1.8 1.8 0 1 0 0 3.6v2.4H12a1.8 1.8 0 1 1-3.6 0H4.4V9.2h2.4a1.8 1.8 0 1 0 0-3.6V4.4zM14.6 12.8h5v6.8h-5v-2.4a1.8 1.8 0 1 1-3.6 0v2.4"/></svg></span>Technical Details</a>
          <a data-v="versions"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.4 4.4h7l8.2 8.2-7 7-8.2-8.2zM8.2 8.2h.01"/></svg></span>Version Control</a>
        </div>
        <div class="nav-group"><div class="nav-group-label">Administrator Tools</div>
          <a data-v="guideddemo"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.6 6.4h16.8v13.2H3.6zM3.6 10.6h16.8M7.4 6.4 5.4 10.6M12 6.4l-2 4.2M16.6 6.4l-2 4.2"/></svg></span>Guided Demo</a>
          <a data-v="admin"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2.1-1.2l-.3-2.4h-4l-.3 2.4a7 7 0 0 0-2.1 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2.1 1.2l.3 2.4h4l.3-2.4a7 7 0 0 0 2.1-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/></svg></span>Admin</a>
          <a data-v="usermgmt" id="navUserMgmt" style="display:none"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.4 19.4v-1.8a3.6 3.6 0 0 0-3.6-3.6H6.6A3.6 3.6 0 0 0 3 17.6v1.8M9.2 4.6a3.4 3.4 0 1 1 0 6.8 3.4 3.4 0 0 1 0-6.8M21 19.4v-1.8a3.6 3.6 0 0 0-2.7-3.5M15.8 4.7a3.6 3.6 0 0 1 0 6.9"/></svg></span>User Management</a>
          <a data-v="adminchange" id="navAdminChange" style="display:none"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.6 4.6 19.4 8.4 8.8 19H5v-3.8zM13.8 6.4l3.8 3.8"/></svg></span>Admin Change</a>
          <a data-v="aicontrol"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 4.2a3 3 0 0 0-3 3 3 3 0 0 0-1.6 5.3A3 3 0 0 0 7.2 18a3 3 0 0 0 4.8 1.4V4.9a3 3 0 0 0-2.6-.7zM14.6 4.2a3 3 0 0 1 3 3 3 3 0 0 1 1.6 5.3A3 3 0 0 1 16.8 18a3 3 0 0 1-4.8 1.4"/></svg></span>AI Control</a>
          <a data-v="config" id="navConfig" style="display:none"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8.6h5.6M14.4 8.6H20M4 15.4h9.6M18.4 15.4H20M12 6.2v4.8M16.8 13v4.8"/></svg></span>Configuration</a>
          <a data-v="settings"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2.1-1.2l-.3-2.4h-4l-.3 2.4a7 7 0 0 0-2.1 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2.1 1.2l.3 2.4h4l.3-2.4a7 7 0 0 0 2.1-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/></svg></span>Settings</a>
          <a data-v="language"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4a8.6 8.6 0 1 1 0 17.2 8.6 8.6 0 0 1 0-17.2M3.4 12h17.2M12 3.4a13 13 0 0 1 0 17.2 13 13 0 0 1 0-17.2"/></svg></span>Translation workbench</a>
          <a data-v="feedback"><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.4 12.6a7.4 7.4 0 0 1-8 7.4L4.6 21l1-3.8a7.4 7.4 0 1 1 14.8-4.6z"/></svg></span>Feedback</a>
          <select id="langSel" class="lang-select" onchange="setLang(this.value)" title="Display language">
            <option value="en">English</option>
            <option value="zh">中文</option>
            <option value="es">Español</option>
            <option value="ar">العربية</option>
            <option value="fr">Français</option>
            <option value="de">Deutsch</option>
            <option value="ja">日本語</option>
            <option value="pt">Português</option>
            <option value="ru">Русский</option>
            <option value="hi">हिन्दी</option>
          </select>
        </div>
      </nav>
    </aside>
    <main id="view" role="main"></main>
  </div>
</div>

<div id="modalRoot"></div>
<div id="flashRoot" aria-live="polite" role="status"></div>

<script src="/static/app.js" defer></script>

</body>
</html>"""


@ui.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE.replace('/static/app.js"', f'/static/app.js?v={_APP_JS_VER}"')
