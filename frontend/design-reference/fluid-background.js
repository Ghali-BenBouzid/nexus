// ============================================================
//  NEXUS — Living Fluid background
//  Vanilla Three.js port of the react-three-fiber "LivingFluidHero"
//  shader: simplex-noise displaced icosahedron, mouse-reactive,
//  fresnel rim, dark(violet)/light(amber) palettes, bloom.
// ============================================================
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

const PALETTE = {
  dark:  { a: new THREE.Color('#8A2BE2'), b: new THREE.Color('#4B0082'), bloom: 0.55, threshold: 0.55, clear: 0x060409, blending: THREE.AdditiveBlending, transparent: true },
  light: { a: new THREE.Color('#ffae00'), b: new THREE.Color('#ff5e00'), bloom: 0.22, threshold: 0.40, clear: 0xfaf7f2, blending: THREE.NormalBlending, transparent: false },
};

const vertexShader = /* glsl */`
  uniform float uTime;
  uniform vec2 uMouse;
  varying vec3 vNormal;

  vec3 mod289(vec3 x){ return x - floor(x*(1.0/289.0))*289.0; }
  vec4 mod289(vec4 x){ return x - floor(x*(1.0/289.0))*289.0; }
  vec4 permute(vec4 x){ return mod289(((x*34.0)+1.0)*x); }
  vec4 taylorInvSqrt(vec4 r){ return 1.79284291400159 - 0.85373472095314*r; }
  float snoise(vec3 v){
    const vec2 C = vec2(1.0/6.0, 1.0/3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
        i.z + vec4(0.0, i1.z, i2.z, 1.0))
        + i.y + vec4(0.0, i1.y, i2.y, 1.0))
        + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0*floor(p*ns.z*ns.z);
    vec4 x_ = floor(j*ns.z);
    vec4 y_ = floor(j - 7.0*x_);
    vec4 x = x_*ns.x + ns.yyyy;
    vec4 y = y_*ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0)*2.0 + 1.0;
    vec4 s1 = floor(b1)*2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
    p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
    vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
    m = m*m;
    return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
  }

  void main(){
    vNormal = normalize(normalMatrix * normal);
    float mouseDist = distance(position.xy, uMouse * 2.0);
    float displacement = snoise(position * 2.5 + uTime * 0.2) * 0.3;
    displacement -= smoothstep(0.0, 1.5, mouseDist) * 0.5;
    vec3 newPosition = position + normal * displacement;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(newPosition, 1.0);
  }
`;

const fragmentShader = /* glsl */`
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  varying vec3 vNormal;
  void main(){
    // true rim light: bright at the silhouette edge, body keeps its colour
    float rim = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 2.2);
    vec3 color = mix(uColorA, uColorB, vNormal.y * 0.5 + 0.5);
    gl_FragColor = vec4(color * 0.85 + rim * 0.45, 1.0);
  }
`;

(function initFluid() {
  const canvas = document.getElementById('fluid-canvas');
  if (!canvas) return;

  const initialTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  let pal = PALETTE[initialTheme] || PALETTE.dark;
  let currentTheme = (PALETTE[initialTheme] ? initialTheme : 'dark');

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearColor(pal.clear, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.set(0, 0, 4);

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) },
      uColorA: { value: pal.a.clone() },
      uColorB: { value: pal.b.clone() },
    },
    blending: pal.blending,
    transparent: pal.transparent,
  });

  const geometry = new THREE.IcosahedronGeometry(1.5, 48);
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  // Post-processing (bloom)
  let composer = null;
  let bloomPass = null;
  try {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    bloomPass = new UnrealBloomPass(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      pal.bloom, 0.55, pal.threshold
    );
    composer.addPass(bloomPass);
    composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    composer.setSize(window.innerWidth, window.innerHeight);
  } catch (e) {
    composer = null; // fall back to direct render
  }

  // Mouse
  const mouse = new THREE.Vector2(0, 0);
  const target = new THREE.Vector2(0, 0);
  window.addEventListener('mousemove', (e) => {
    target.x = (e.clientX / window.innerWidth) * 2 - 1;
    target.y = -(e.clientY / window.innerHeight) * 2 + 1;
  });

  // Resize
  function onResize() {
    const w = window.innerWidth, h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    if (composer) composer.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  // Theme switching (exposed to the React app)
  window.setFluidTheme = function (theme) {
    pal = PALETTE[theme] || PALETTE.dark;
    currentTheme = (PALETTE[theme] ? theme : 'dark');
    renderer.setClearColor(pal.clear, 1);
    material.uniforms.uColorA.value.copy(pal.a);
    material.uniforms.uColorB.value.copy(pal.b);
    material.blending = pal.blending;
    material.transparent = pal.transparent;
    material.needsUpdate = true;
    if (bloomPass) { bloomPass.strength = pal.bloom; bloomPass.threshold = pal.threshold; }
  };

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    mouse.lerp(target, 0.05);
    material.uniforms.uTime.value = t;
    material.uniforms.uMouse.value.copy(mouse);
    mesh.rotation.y += 0.0014;
    mesh.rotation.x = Math.sin(t * 0.12) * 0.12;
    // Bloom only in dark mode — a bright (light) background would bloom itself.
    if (composer && currentTheme === 'dark') composer.render();
    else renderer.render(scene, camera);
  }
  animate();
  window.__fluidReady = true;
})();
