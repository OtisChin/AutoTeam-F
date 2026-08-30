var SentinelSDK=function(t){
class _{async getRequirementsToken(){return "requirements-old"}async getEnforcementToken(){return "final-old"}}
var P=new _;
const I=new WeakMap;function D(t,n){I.set(t,n)}function $(t){return I.get(t)}
async function _n(t,n){return $(t)+":"+n}
async function ye(t){const e={turnstile:{dx:"dx"}};return e.turnstile.dx?await _n(e,e.turnstile.dx):null}
return t.init=function(){},t.token=ye,t}({});
