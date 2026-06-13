// Living-fluid WebGL background, ported nearly verbatim from the handoff's
// fluid-background.js. Simplex-noise displaced icosahedron, mouse-reactive,
// fresnel rim, dark(violet)/light(amber) palettes, bloom in dark mode only.
// Exposes init -> { setTheme, dispose } instead of window globals.
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";

import type { Theme } from "../types";

type Palette = {
  a: THREE.Color;
  b: THREE.Color;
  bloom: number;
  threshold: number;
  clear: number;
  blending: THREE.Blending;
  transparent: boolean;
};

const PALETTE: Record<Theme, Palette> = {
  dark: {
    a: new THREE.Color("#8A2BE2"),
    b: new THREE.Color("#4B0082"),
    bloom: 0.55,
    threshold: 0.55,
    clear: 0x060409,
    blending: THREE.AdditiveBlending,
    transparent: true,
  },
  light: {
    a: new THREE.Color("#ffae00"),
    b: new THREE.Color("#ff5e00"),
    bloom: 0.22,
    threshold: 0.4,
    clear: 0xfaf7f2,
    blending: THREE.NormalBlending,
    transparent: false,
  },
};

const vertexShader = /* glsl */ `
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

const fragmentShader = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  varying vec3 vNormal;
  void main(){
    float rim = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 2.2);
    vec3 color = mix(uColorA, uColorB, vNormal.y * 0.5 + 0.5);
    gl_FragColor = vec4(color * 0.85 + rim * 0.45, 1.0);
  }
`;

export type FluidHandle = {
  setTheme: (theme: Theme) => void;
  // Override the blob's gradient colors (Design Lab): the theme still drives
  // bloom/clear/blending, but the two blob colors come from the chosen palette.
  setPalette: (a: string, b: string) => void;
  // Adjust the dark-mode bloom (glow) strength. Light mode renders without bloom.
  setBloom: (strength: number) => void;
  // Override the renderer clear color, so the backdrop can adapt to the palette.
  setBackground: (hex: string) => void;
  dispose: () => void;
};

export function initFluidBackground(
  canvas: HTMLCanvasElement,
  initialTheme: Theme,
): FluidHandle {
  let currentTheme: Theme = PALETTE[initialTheme] ? initialTheme : "dark";
  let pal = PALETTE[currentTheme];

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearColor(pal.clear, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    75,
    window.innerWidth / window.innerHeight,
    0.1,
    100,
  );
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

  let composer: EffectComposer | null = null;
  let bloomPass: UnrealBloomPass | null = null;
  try {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    bloomPass = new UnrealBloomPass(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      pal.bloom,
      0.55,
      pal.threshold,
    );
    composer.addPass(bloomPass);
    composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    composer.setSize(window.innerWidth, window.innerHeight);
  } catch {
    composer = null; // fall back to direct render
  }

  const mouse = new THREE.Vector2(0, 0);
  const target = new THREE.Vector2(0, 0);
  const onMouseMove = (e: MouseEvent) => {
    target.x = (e.clientX / window.innerWidth) * 2 - 1;
    target.y = -(e.clientY / window.innerHeight) * 2 + 1;
  };
  window.addEventListener("mousemove", onMouseMove);

  const onResize = () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer?.setSize(w, h);
  };
  window.addEventListener("resize", onResize);

  // Design Lab overrides: blob colors + an adjustable dark-mode glow strength.
  let overrideA: THREE.Color | null = null;
  let overrideB: THREE.Color | null = null;
  let darkBloom = PALETTE.dark.bloom;

  const applyVfx = () => {
    material.blending = pal.blending;
    material.transparent = pal.transparent;
    material.needsUpdate = true;
    if (bloomPass) {
      // Bloom only renders in dark mode; use the adjustable strength there.
      bloomPass.strength = currentTheme === "dark" ? darkBloom : pal.bloom;
      bloomPass.threshold = pal.threshold;
    }
  };

  const setTheme = (theme: Theme) => {
    pal = PALETTE[theme] || PALETTE.dark;
    currentTheme = PALETTE[theme] ? theme : "dark";
    renderer.setClearColor(pal.clear, 1);
    material.uniforms.uColorA.value.copy(overrideA ?? pal.a);
    material.uniforms.uColorB.value.copy(overrideB ?? pal.b);
    applyVfx();
  };

  const setPalette = (a: string, b: string) => {
    overrideA = new THREE.Color(a);
    overrideB = new THREE.Color(b);
    material.uniforms.uColorA.value.copy(overrideA);
    material.uniforms.uColorB.value.copy(overrideB);
  };

  const setBloom = (strength: number) => {
    darkBloom = strength;
    if (bloomPass && currentTheme === "dark") bloomPass.strength = strength;
  };

  const setBackground = (hex: string) => {
    renderer.setClearColor(new THREE.Color(hex).getHex(), 1);
  };

  const clock = new THREE.Clock();
  let raf = 0;
  const renderFrame = () => {
    // Bloom (the composer) renders in dark mode only; a bright background blooms
    // itself and washes the scene.
    if (composer && currentTheme === "dark") composer.render();
    else renderer.render(scene, camera);
  };
  const animate = () => {
    raf = requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    mouse.lerp(target, 0.05);
    material.uniforms.uTime.value = t;
    material.uniforms.uMouse.value.copy(mouse);
    mesh.rotation.y += 0.0014;
    mesh.rotation.x = Math.sin(t * 0.12) * 0.12;
    // Bloom only in dark mode, a bright background would bloom itself.
    renderFrame();
  };
  // Respect reduced-motion: render one static frame instead of an endless loop.
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    material.uniforms.uTime.value = 1.2;
    renderFrame();
  } else {
    animate();
  }

  const dispose = () => {
    cancelAnimationFrame(raf);
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("resize", onResize);
    geometry.dispose();
    material.dispose();
    composer?.dispose();
    renderer.dispose();
  };

  return { setTheme, setPalette, setBloom, setBackground, dispose };
}
