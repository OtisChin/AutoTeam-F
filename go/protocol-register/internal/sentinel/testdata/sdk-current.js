var SentinelSDK=function(t){
class O{async getRequirementsToken(){return "requirements-current"}async getEnforcementToken(){return "final-current"}}
var E=new O;
function j(){const t=["get","set"];return(j=function(){return t})()}
const U=new WeakMap;function I(t,n){const e=j();return(I=function(t,n){return e[t-=0]})(t,n)}
function D(t,n){U[I(1)](t,n)}function F(t){return U[I(0)](t)}
async function Rn(t,n){return F(t)+":"+n}
async function je(t){const e={turnstile:{dx:"dx"}};return e.turnstile.dx?await Rn(e,e.turnstile.dx):null}
return t.timing=function(){return null},t.token=je,t}({});
