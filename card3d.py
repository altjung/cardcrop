"""A card you can hold: the front and back photos on a real rounded, slightly thick card
in OpenGL, turned by dragging (all the way round), with a holo foil and a glare that
follow the angle, the way light moves across the real thing.

GLSL 1.20 on purpose: it is what macOS gives a plain Qt OpenGL widget, and every
other driver still accepts it."""
from __future__ import annotations

import math
import os
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture
from PySide6.QtOpenGLWidgets import QOpenGLWidget

CARD_H = 2.0
CARD_W = CARD_H * 63 / 88
THICK = CARD_H * 0.32 / 88           # a real card is about 0.3 mm thick
RADIUS = CARD_H * 3.2 / 88          # a real card's corner, 3 mm-ish on 88 mm

VERT = """
#version 120
attribute vec3 aPos;
attribute vec3 aNor;
attribute vec2 aUv;
attribute float aFace;
uniform mat4 uMvp;
uniform mat4 uMv;
uniform mat3 uNorm;
varying vec2 vUv;
varying vec3 vN;
varying float vFace;
varying vec3 vPosV;
void main() {
    gl_Position = uMvp * vec4(aPos, 1.0);
    vN = normalize(uNorm * aNor);
    vUv = aUv;
    vFace = aFace;
    vPosV = (uMv * vec4(aPos, 1.0)).xyz;
}
"""

FRAG = """
#version 120
uniform sampler2D uFront;
uniform sampler2D uBack;
uniform float uHolo;
uniform float uMode;
uniform float uTime;
uniform vec2 uTilt;
uniform vec3 uLight;
uniform vec3 uEdge;
uniform float uPattern;
uniform float uDisp;
uniform float uFreq;
uniform float uSat;
uniform float uResp;
uniform float uSparkle;
uniform float uLightMode;      // 0 classic, 1 studio, 2 soft box, 3 dramatic, 4 sunset
uniform float uGloss;
uniform float uExposure;
uniform vec4 uShadow;
uniform sampler2D uMatte;      // layers: the subject's matte
uniform sampler2D uBgTex;      // layers: the art with the subject filled out
uniform sampler2D uArt;        // your own layers: the subject over the backdrop, without the frame
uniform sampler2D uFrames;     // your own layers: the frames over the backdrop, without the subject
uniform float uManual;
uniform float uLayers;         // 1 when the face is split into frame, background and subject
uniform vec4 uLayerA;          // depth, frame width, subject light, background light
uniform vec3 uLayerFoil;       // foil on the frame, the background, the subject
uniform vec3 uCenter;        // the card's centre, in view space          // half width, half height, blur, strength (the drop shadow pass)
varying vec2 vUv;
varying vec3 vN;
varying float vFace;
varying vec3 vPosV;

vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
uniform sampler2D uEnv;        // the room the card reflects: your backdrop photo or a studio
uniform float uEnvAmt;         // 0 the drawn softboxes only, 1 the room
uniform mat3 uNorm;
uniform vec2 uDrift;           // the lights drifting round the card: radians round the vertical, then the level            // the card's turn, to see the view from the card's side
uniform vec4 uFloor;           // the floor mirror: on, floor height, fade length, strength
uniform float uDof;            // depth of field: how out of focus the backdrop is, 0 = sharp
uniform float uNS;             // how many parallax layers are bound
//STACKDECL//
// the backdrop seen through a lens focused on the subject: a soft disc blur, two rings of taps
vec3 backdrop(vec2 uv) {
    vec3 c = texture2D(uBgTex, uv).rgb;
    if (uDof <= 0.0) return c;
    float r = uDof * 0.014;
    vec3 acc = c;
    float n = 1.0;
    for (int i = 0; i < 16; i++) {
        float a = float(i) * 2.399963;               // golden angle: an even disc, no rings
        float d = sqrt((float(i) + 0.5) / 16.0) * r;
        acc += texture2D(uBgTex, uv + vec2(cos(a), sin(a) / 1.396) * d).rgb;
        n += 1.0;
    }
    return acc / n;
}

vec3 drift(vec3 p) {
    float cy = cos(uDrift.x), sy = sin(uDrift.x), cx = cos(uDrift.y), sx = sin(uDrift.y);
    p = vec3(cy * p.x + sy * p.z, p.y, -sy * p.x + cy * p.z);
    return vec3(p.x, cx * p.y - sx * p.z, sx * p.y + cx * p.z);
}

mat3 transpose3(mat3 m) {        // GLSL 1.20 on some Macs has no transpose()
    return mat3(m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2]);
}

vec2 envUv(vec3 R) {            // a sphere map: straight back at the camera is the middle of the room
    float m = 2.0 * sqrt(R.x * R.x + R.y * R.y + (R.z + 1.0) * (R.z + 1.0));
    return vec2(R.x, R.y) / max(m, 1e-3) + 0.5;
}

void shade() {
    if (vFace > 2.5) {                       // the soft shadow the card throws on the backdrop
        vec2 q = abs(vUv) - uShadow.xy + vec2(0.06);
        float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.06;
        float a = (1.0 - smoothstep(-uShadow.z, uShadow.z, sd)) * uShadow.w;
        gl_FragColor = vec4(0.0, 0.0, 0.0, a);
        return;
    }
    vec3 N = normalize(vN);
    vec3 V = normalize(-vPosV);
    vec3 L = normalize(uLight);
    if (dot(N, V) < 0.0 && vFace < 1.5) N = -N;   // the side you see faces you
    if (vFace > 1.5 && uLightMode > 0.5) {   // edge, lit like the face
        vec3 e = uEdge * (0.35 + 0.65 * max(dot(N, normalize(vec3(0.45, 0.6, 0.8))), 0.0));
        gl_FragColor = vec4(e, 1.0);
        return;
    }
    if (vFace > 1.5) {                       // the card's edge: thin white core stock
        float d = 0.55 + 0.45 * max(dot(N, L), 0.0);
        gl_FragColor = vec4(uEdge * d, 1.0);
        return;
    }
    vec4 base = vFace < 0.5 ? texture2D(uFront, vUv) : texture2D(uBack, vUv);
    float layerFoil = 1.0;
    float layerLift = 1.0;
    if (vFace < 0.5 && uLayers > 0.5) {
        // the frame (border, name bar, rule box) stays on the surface; the art behind it is a
        // window: the background sits deep and slides one way, the subject floats and slides the other
        float fw = uLayerA.y;
        float fx = fw, fy = fw * 0.716;
        float ring = 1.0 - smoothstep(fx - 0.004, fx + 0.004, min(vUv.x, 1.0 - vUv.x))
                         * smoothstep(fy - 0.004, fy + 0.004, min(vUv.y, 1.0 - vUv.y));
        float bars = smoothstep(0.888, 0.896, vUv.y) + (1.0 - smoothstep(0.086, 0.094, vUv.y));
        if (fw <= 0.0) { ring = 0.0; bars = 0.0; }      // your own frame PNG says where the frame is
        float fm = clamp(max(max(ring, bars), texture2D(uMatte, vUv).g), 0.0, 1.0);   // text stays put
        // parallax from where the camera really is: the line of sight at this very point, in the card's
        // own axes, so a camera close in or off to one side shifts the layers as a real one would
        vec3 Vl = transpose3(uNorm) * normalize(-vPosV);
        vec2 look = clamp(vec2(-Vl.x, Vl.y) / max(abs(Vl.z), 0.3), vec2(-1.6), vec2(1.6));
        vec2 off = look * uLayerA.x * 0.055;
        vec2 bgUv = vec2(0.5) + (vUv - vec2(0.5)) * (1.0 - uLayerA.x * 0.06) + off;
        vec2 fgUv = vUv - off * 0.55;
        if (uManual > 0.5 && uNS > 0.5) {
            // your own stack, every layer at its own depth: the backdrop deepest, the card's own
            // frame on the surface, the rest in between or floating above, each sliding at its own speed
            vec3 col = backdrop(bgUv);
            float lf = uLayerFoil.y, ll = uLayerA.w;
//STACK//
            base = vec4(col, 1.0);
            layerFoil = lf;
            layerLift = ll;
        } else if (uManual > 0.5) {
            // your own stack: frames above the subject cover it, frames below it sit under it
            vec3 mt = texture2D(uMatte, vUv).rgb;
            float above = mt.g, below = mt.b, fall = max(above, below);
            float sa = texture2D(uMatte, fgUv).r * (1.0 - above);
            vec3 bgc = backdrop(bgUv);
            float sh = texture2D(uMatte, fgUv + off * 0.9 + vec2(0.006, -0.008)).r * (1.0 - fall);
            bgc *= 1.0 - 0.28 * sh * uLayerA.x;
            vec3 under = mix(bgc, texture2D(uFrames, vUv).rgb, fall);
            base = vec4(mix(under, texture2D(uArt, fgUv).rgb, sa), 1.0);
            layerFoil = (1.0 - sa) * (fall * uLayerFoil.x + (1.0 - fall) * uLayerFoil.y) + sa * uLayerFoil.z;
            layerLift = (1.0 - sa) * mix(uLayerA.w, 1.0, fall) + sa * uLayerA.z;
        } else {
        float a = texture2D(uMatte, fgUv).r * (1.0 - fm);
        // the subject's colour from the art alone: taken from the finished face, a shifted subject
        // would pick up the frame's text printed over it
        vec3 fgCol = uManual > 0.5 ? texture2D(uArt, fgUv).rgb : texture2D(uFront, fgUv).rgb;
        vec3 art = mix(backdrop(bgUv), fgCol, a);
        // a little ambient shadow from the subject onto the background behind it
        float occl = texture2D(uMatte, fgUv + off * 0.9 + vec2(0.006, -0.008)).r * (1.0 - a);
        art *= 1.0 - 0.28 * occl * uLayerA.x;
        base = vec4(mix(art, base.rgb, fm), 1.0);
        layerFoil = fm * uLayerFoil.x + (1.0 - fm) * ((1.0 - a) * uLayerFoil.y + a * uLayerFoil.z);
        layerLift = mix(mix(uLayerA.w, uLayerA.z, a), 1.0, fm);
        }
    }
    float diff = 0.82 + 0.18 * max(dot(N, L), 0.0);
    vec3 col = base.rgb * diff * layerLift;
    float ang = uTilt.x * 1.7 + uTilt.y * 1.2;
    if (vFace < 0.5 && uHolo > 0.0) {
        // the art window on a standard card, measured from the top: 11% to 53% down, 8% in
        float inArt = step(0.075, vUv.x) * step(vUv.x, 0.925) * step(0.47, vUv.y) * step(vUv.y, 0.895);
        float mask = uMode < 0.5 ? 1.0 : (uMode < 1.5 ? inArt : 1.0 - inArt);
        float a = ang * uResp;
        vec2 q = vUv - (vec2(0.5) + uTilt * vec2(0.35, 0.30) * uResp);   // the radiating patterns' centre follows the light
        q.x *= 0.716;
        float hue, bands;
        if (uPattern < 0.5) {                       // linear: diagonal bands, the classic sheen
            hue = (vUv.x * 0.85 + vUv.y * 0.65) * uDisp + a;
            bands = sin((vUv.x * 1.25 + vUv.y) * uFreq + a * 14.0);
        } else if (uPattern < 1.5) {                // radial: rings spreading out from a centre
            float r = length(q);
            hue = r * 2.2 * uDisp - a;
            bands = sin(r * uFreq * 1.6 - a * 14.0);
        } else if (uPattern < 2.5) {                // sunburst: rays out from a centre
            float th = atan(q.y, q.x) / 6.28318;
            hue = th * 2.0 * uDisp + length(q) * 0.6 * uDisp + a;
            bands = sin(th * floor(uFreq * 0.9 + 4.0) * 6.28318 + a * 6.0);
        } else if (uPattern < 3.5) {                // cracked ice: shards, each catching its own colour
            vec2 g = vUv * vec2(uFreq * 0.22 + 2.0, (uFreq * 0.22 + 2.0) * 1.4);
            vec2 id = floor(g), best = id;
            float dmin = 9.0;
            for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
                vec2 c = id + vec2(float(i), float(j));
                vec2 pt = c + vec2(hash(c), hash(c + 3.1));
                float dd = length(g - pt);
                if (dd < dmin) { dmin = dd; best = c; }
            }
            hue = hash(best) * 3.0 * uDisp + a * 1.5;
            bands = sin(hash(best + 9.0) * 40.0 + a * 20.0);
        } else {                                    // glitter: a fine field of flecks
            vec2 c = floor(vUv * vec2(uFreq * 3.0 + 40.0, (uFreq * 3.0 + 40.0) * 1.4));
            hue = (vUv.x * 0.6 + vUv.y * 0.5) * uDisp + hash(c) * 0.35 * uDisp + a;
            bands = step(0.55, hash(c + floor(a * 6.0))) * 2.0 - 1.0;
        }
        vec3 rainbow = hsv2rgb(vec3(fract(hue), uSat, 1.0));
        bands = 0.5 + 0.5 * bands;
        float lum = dot(base.rgb, vec3(0.299, 0.587, 0.114));
        float tiltAmt = clamp(length(uTilt) * 2.2 * max(uResp, 0.2), 0.0, 1.0);
        vec3 roomF = texture2D(uEnv, envUv(drift(reflect(-V, N))), 3.0).rgb;
        float roomL = dot(roomF, vec3(0.299, 0.587, 0.114));
        float k = uHolo * mask * layerFoil * (0.3 + 0.7 * smoothstep(0.1, 0.85, lum)) * (0.5 + 0.5 * bands)
                  * (0.35 + 0.65 * tiltAmt) * mix(1.0, 0.35 + 1.4 * roomL, uEnvAmt);
        rainbow = mix(rainbow, rainbow * (0.75 + 0.5 * roomF / max(roomL, 0.05)), 0.35 * uEnvAmt);
        vec3 screen = 1.0 - (1.0 - col) * (1.0 - rainbow * k);
        col = mix(col, screen, 0.9);
        vec2 cell = floor(vUv * vec2(240.0, 335.0));
        float sp = step(1.0 - 0.012 * uSparkle, hash(cell)) * k
                   * (0.5 + 0.5 * sin(uTime * 2.5 + hash(cell + 7.0) * 40.0 + ang * 22.0));
        col += vec3(sp) * 0.9 * min(1.0, uSparkle * 2.0);
    }
    if (uLightMode < 0.5) {
        // classic: glare that slides across the face as the card turns
        vec2 gp = vec2(0.5) + uTilt * vec2(1.1, 0.9);
        vec2 d = vUv - gp;
        float g = exp(-dot(d, d) * 5.0);
        vec3 R = reflect(-L, N);
        float spec = pow(max(dot(R, V), 0.0), 28.0);
        float onBack = vFace > 0.5 ? 0.6 : 1.0;           // a card's back has a softer satin coat
        col += vec3(1.0) * (g * 0.16 + spec * 0.22) * onBack;
        gl_FragColor = vec4(col, 1.0);
        return;
    }
    // ---- studio lighting: linear light, a key, a fill and a rim, GGX highlights,
    // a softbox reflected in the laminate, Fresnel at grazing angles, filmic tone curve
    vec3 alb = pow(col / max(diff, 0.001), vec3(2.2));        // undo the classic shading, to linear
    // lights are lamps placed round the card (positions in card heights from its centre), so
    // they fall off across the face: a bright corner, a darker one, the way a real shot looks
    vec3 Pk, Pf, Pr; vec3 Ck, Cf, Cr; float amb;
    if (uLightMode < 1.5) {          // studio: key high on the left, soft fill right, cool rim behind
        Pk = vec3(-1.3, 1.5, 1.7);  Ck = vec3(1.0, 0.97, 0.92) * 1.55;
        Pf = vec3(1.8, -0.3, 1.6);  Cf = vec3(0.85, 0.9, 1.0) * 0.35;
        Pr = vec3(0.6, 1.4, -1.5);  Cr = vec3(0.8, 0.9, 1.0) * 1.0; amb = 0.12;
    } else if (uLightMode < 2.5) {   // soft box: a big light straight in front, low contrast
        Pk = vec3(0.0, 0.6, 2.6);   Ck = vec3(1.0) * 1.25;
        Pf = vec3(-2.0, 0.0, 1.6);  Cf = vec3(1.0) * 0.30;
        Pr = vec3(0.0, 1.8, -1.2);  Cr = vec3(1.0) * 0.35; amb = 0.26;
    } else if (uLightMode < 3.5) {   // dramatic: a hard key low from the side, the far side in shadow
        Pk = vec3(-2.2, 0.6, 1.6);  Ck = vec3(1.0, 0.95, 0.88) * 2.3;
        Pf = vec3(1.8, 0.0, 1.4);   Cf = vec3(0.6, 0.7, 1.0) * 0.05;
        Pr = vec3(1.2, 1.0, -1.2);  Cr = vec3(0.7, 0.85, 1.0) * 1.8; amb = 0.02;
    } else {                         // sunset: a warm low key, a violet fill
        Pk = vec3(-1.7, 0.2, 1.3);  Ck = vec3(1.0, 0.68, 0.40) * 1.9;
        Pf = vec3(1.6, 0.9, 1.4);   Cf = vec3(0.55, 0.45, 1.0) * 0.55;
        Pr = vec3(0.3, 1.5, -1.4);  Cr = vec3(1.0, 0.6, 0.8) * 0.8; amb = 0.06;
    }
    // the back is printed stock with a satin coat: softer gloss than the face, no foil
    float gloss = vFace > 0.5 ? 0.25 + 0.45 * uGloss : uGloss;
    float rough = vFace > 0.5 ? mix(0.66, 0.42, gloss) : mix(0.62, 0.30, gloss);   // never mirror-sharp
    float a2 = rough * rough * rough * rough;
    vec3 F0 = vec3(vFace > 0.5 ? 0.038 : 0.045);
    vec3 lit = alb * amb;
    vec3 spec = vec3(0.0);
    vec3 Ps[3]; vec3 Cs[3];
    Ps[0] = drift(Pk); Ps[1] = drift(Pf); Ps[2] = drift(Pr); Cs[0] = Ck; Cs[1] = Cf; Cs[2] = Cr;
    float NV = max(dot(N, V), 0.001);
    // near edge-on the face is a sliver and the maths of glossy highlights runs away: fade the
    // highlights out as the card turns edge-on, so a turn never flashes
    float face = smoothstep(0.2, 0.65, NV);
    float NVs = max(NV, 0.25);
    for (int i = 0; i < 3; i++) {
        vec3 d = uCenter + Ps[i] * 2.0 - vPosV;          // 2.0: one card height in scene units
        float r2 = dot(d, d);
        vec3 Li = d / sqrt(r2);
        float att = 9.0 / (r2 + 1.0);                    // soft inverse-square, about 1 at the card
        float NL = max(dot(N, Li), 0.0);
        vec3 H = normalize(Li + V);
        float NH = max(dot(N, H), 0.0);
        float dd = NH * NH * (a2 - 1.0) + 1.0;
        float D = a2 / (3.14159 * dd * dd);
        vec3 F = F0 + (1.0 - F0) * pow(1.0 - max(dot(H, V), 0.0), 5.0);
        float k = (rough + 1.0) * (rough + 1.0) / 8.0;
        float G = (NL / (NL * (1.0 - k) + k)) * (NVs / (NVs * (1.0 - k) + k));
        spec += min(D * F * G / max(4.0 * NL * NVs, 0.05), 2.5) * Cs[i] * NL * att;
        lit += alb * Cs[i] * NL * att * (1.0 - F);
    }
    vec3 R = drift(reflect(-V, N));
    // narrow strips, so on a flat card they read as a band of light crossing it, not a wash
    float box = exp(-pow(abs(R.x + 0.30) / 0.16, 2.0) - pow(abs(R.y - 0.25) / 0.45, 6.0))
              + 0.5 * exp(-pow(abs(R.x - 0.42) / 0.12, 2.0) - pow(abs(R.y + 0.05) / 0.6, 6.0));
    float fres = 0.04 + 0.96 * pow(1.0 - NV, 5.0);
    vec3 env = vec3(1.0) * box * mix(0.06, 0.32, gloss) * (0.7 + 0.8 * fres) * (vFace > 0.5 ? 0.55 : 1.0);
    // the room in the laminate: blurrier the rougher the finish, stronger at grazing angles
    vec3 room = pow(texture2D(uEnv, envUv(R), 1.0 + rough * 6.0).rgb, vec3(2.2));
    vec3 envR = room * mix(0.10, 0.55, gloss) * (0.55 + 1.2 * fres) * (vFace > 0.5 ? 0.5 : 1.0);
    env = mix(env, envR + env * 0.35, uEnvAmt);
    // a touch of occlusion toward the rim: light falls off a little at the card's edges
    vec2 eu = abs(vUv - 0.5) * 2.0;
    float occ = 1.0 - 0.10 * smoothstep(0.82, 1.0, max(eu.x, eu.y));
    vec3 c = (lit * occ + (min(spec, vec3(0.55)) + env) * face) * uExposure;
    c = (c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14);   // filmic (ACES fit)
    gl_FragColor = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)), 1.0);
}

void main() {
    if (uFloor.x > 0.5 && vPosV.y > uFloor.y) discard;      // the mirror image stays under the floor
    shade();
    if (uFloor.x > 0.5) {
        float d = clamp((uFloor.y - vPosV.y) / uFloor.z, 0.0, 1.0);
        float a = uFloor.w * (1.0 - d) * (1.0 - d);
        gl_FragColor = vec4(gl_FragColor.rgb * 0.9, a);
    }
}
"""


STACK_N = 6                       # parallax layers the shader takes (layers.MAX_STACK)
STACK_UNIT = 6                    # texture units 6.. hold them


def _stack_glsl():
    decl, body = [], []
    for i in range(STACK_N):
        decl.append(f"uniform sampler2D uS{i};\nuniform float uSD{i};\nuniform float uSK{i};")
        body.append(f"""            if (uNS > {i}.5) {{
                vec2 uv{i} = vUv + off * uSD{i};
                vec4 c{i} = texture2D(uS{i}, uv{i});          // premultiplied
                if (uSK{i} > 0.5) {{                            // the subject shades what is under it
                    float sh{i} = texture2D(uS{i}, uv{i} + off * 0.9 + vec2(0.006, -0.008)).a;
                    col *= 1.0 - 0.28 * sh{i} * uLayerA.x * (1.0 - c{i}.a);
                }}
                col = col * (1.0 - c{i}.a) + c{i}.rgb;
                lf = mix(lf, uSK{i} > 0.5 ? uLayerFoil.z : uLayerFoil.x, c{i}.a);
                ll = mix(ll, uSK{i} > 0.5 ? uLayerA.z : 1.0, c{i}.a);
            }}""")
    return "\n".join(decl), "\n".join(body)


FRAG = FRAG.replace("//STACKDECL//", _stack_glsl()[0]).replace("//STACK//", _stack_glsl()[1])


DEPTH_FRAG = """
#version 120
varying vec3 vPosV;
void main() { gl_FragColor = vec4(-vPosV.z, 0.0, 0.0, 1.0); }
"""

# a holder round the card: clear acrylic or film that reflects the room, brighter at grazing angles,
# its edges catching light like thick plastic; the slab's label is printed card stock
CASE_FRAG = """
#version 120
uniform sampler2D uEnv;
uniform sampler2D uLabel;
uniform vec3 uTint;
uniform vec4 uLook;            // base alpha, reflection, edge alpha, frost
uniform vec4 uBox;             // the slab in mm: width, height, the card well's centre (up), rim width; 0 for others
uniform vec4 uWells;           // the label well: centre (up), height, width; and the card well's margin (mm)
uniform vec2 uSize;            // the holder in mm
uniform vec2 uThick;           // acrylic over the card, and at the rim (mm): how much light it soaks up
uniform float uPass;           // 1: the body of the plastic, multiplied over what is behind; 0: its surface
uniform float uHaze;           // how milky the plastic is: 0 optical glass
uniform vec4 uRails;           // a top loader's welded rails (mm): sides, bottom, top seam; w > 0 turns them on
uniform float uMouldFace;      // the slab's moulding on: -1 both faces, 0 the front only, 1 the back only
uniform mat3 uNorm;
float hashc(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
uniform vec2 uDrift;
uniform float uExposure;
uniform vec4 uFloor;
varying vec2 vUv;
varying vec3 vN;
varying float vFace;
varying vec3 vPosV;
vec2 envUv(vec3 R) {
    float m = 2.0 * sqrt(R.x * R.x + R.y * R.y + (R.z + 1.0) * (R.z + 1.0));
    return vec2(R.x, R.y) / max(m, 1e-3) + 0.5;
}
vec3 drift(vec3 p) {
    float cy = cos(uDrift.x), sy = sin(uDrift.x), cx = cos(uDrift.y), sx = sin(uDrift.y);
    p = vec3(cy * p.x + sy * p.z, p.y, -sy * p.x + cy * p.z);
    return vec3(p.x, cx * p.y - sx * p.z, sx * p.y + cx * p.z);
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hashc(i), hashc(i + vec2(1.0, 0.0)), f.x), mix(hashc(i + vec2(0.0, 1.0)), hashc(i + vec2(1.0)), f.x), f.y);
}
float rbox(vec2 p, vec2 c, vec2 hs, float r) {
    vec2 q = abs(p - c) - hs + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
// the slab's two recessed windows, over the label and over the card: mm from the nearer one's edge,
// negative inside it
float wells(vec2 p) {
    // the label window only: the card's space below is one open window with no well of its own
    return rbox(p, vec2(0.0, uWells.x), vec2(uWells.z * 0.5 + 0.6, uWells.y * 0.5 + 0.6), 2.0);
}
void shade() {
    vec3 N = normalize(vN);
    vec3 V = normalize(-vPosV);
    bool behind = dot(N, V) < 0.0;
    if (behind) N = -N;
    vec2 pm = (vUv - 0.5) * uSize;                            // mm from the centre
    bool boxed = uBox.x > 0.0 && (uMouldFace < -0.5 || abs(vFace - uMouldFace) < 0.5 || vFace > 1.5);
    vec2 em = uSize * 0.5 - abs(pm);
    float edgeD = min(em.x, em.y);                             // mm in from the outside edge
    // mm in from the slab's rounded outside edge: the rim's step follows the corners round, never square
    float outerD = -rbox(pm, vec2(0.0), uSize * 0.5, 4.0);
    float onRimB = boxed ? 1.0 - smoothstep(uBox.w - 0.2, uBox.w + 0.2, outerD) : 0.0;
    // a slab is frosted everywhere but the card's window, which stays clear
    float divY0 = uWells.x - uWells.y * 0.5 - 0.6 - uBox.z;
    // both halves of a slab, the moulded face and the flat inner sheet behind it alike: frosted plastic
    // everywhere but the two windows, so nothing grey is seen through the label's window from either side
    bool slab = uBox.x > 0.0;
    float inWin = slab ? smoothstep(uBox.w + 1.2, uBox.w + 2.2, outerD) * (1.0 - smoothstep(divY0 - 2.0, divY0 - 1.0, pm.y))
                       : 0.0;
    if (slab) inWin = max(inWin, 1.0 - smoothstep(-1.0, 0.0, wells(pm)));   // the label's window is clear too
    float frost = slab ? mix(2.8, 0.0, inWin) : 1.0;
    // a top loader's two sheets are welded along the left, right and bottom: a band of thicker, bluer
    // plastic there with a fine seam line on its inner side; the open top has only a hairline
    float onRail = 0.0, seam = 0.0;
    if (uRails.w > 0.0) {
        float bw = pm.y > 0.0 ? uRails.z : uRails.y;
        onRail = max(1.0 - smoothstep(uRails.x - 0.12, uRails.x + 0.12, em.x),
                     pm.y < 0.0 ? 1.0 - smoothstep(bw - 0.12, bw + 0.12, em.y) : 0.0);
        float sideLine = 1.0 - smoothstep(0.0, 0.22, abs(em.x - uRails.x));
        float endLine = (1.0 - smoothstep(0.0, 0.22, abs(em.y - bw))) * step(uRails.x - 0.1, em.x);
        seam = max(sideLine * step(bw - 0.1, em.y), endLine * (pm.y > 0.0 ? 0.45 : 1.0));
    }
    // the windows sit a little below the surround: a rounded slope runs down into each, which bends
    // the light like a real moulded step
    float bevelW = 1.8, dW = 1000.0, tilt = 0.0;
    if (boxed && vFace < 1.5) {
        dW = wells(pm);
        float k = clamp(-dW / bevelW, 0.0, 1.0);
        tilt = (dW < 0.0 && dW > -bevelW) ? 3.4 * k * (1.0 - k) : 0.0;
        vec3 T = normalize(uNorm * vec3(1.0, 0.0, 0.0));
        vec3 B = normalize(uNorm * vec3(0.0, 1.0, 0.0));
        float e = 0.08;
        if (tilt > 0.0) {
            vec2 g = normalize(vec2(wells(pm + vec2(e, 0.0)) - wells(pm - vec2(e, 0.0)),
                                    wells(pm + vec2(0.0, e)) - wells(pm - vec2(0.0, e))) + 1e-6);
            N = normalize(N - (g.x * T + g.y * B) * tilt);
        }
        // the rim steps down to the face over a rounded slope, like the windows, not a hard edge
        float rs = (outerD - uBox.w) / 1.4;
        if (rs > 0.0 && rs < 1.0) {
            float rt = 2.6 * rs * (1.0 - rs);
            vec2 g = normalize(vec2(-rbox(pm + vec2(e, 0.0), vec2(0.0), uSize * 0.5, 4.0)
                                    + rbox(pm - vec2(e, 0.0), vec2(0.0), uSize * 0.5, 4.0),
                                    -rbox(pm + vec2(0.0, e), vec2(0.0), uSize * 0.5, 4.0)
                                    + rbox(pm - vec2(0.0, e), vec2(0.0), uSize * 0.5, 4.0)) + 1e-6);
            N = normalize(N + (g.x * T + g.y * B) * rt);
            tilt = max(tilt, rt);
        }
    }
    float NV = max(dot(N, V), 0.0);
    vec3 R = drift(reflect(-V, N));
    vec3 room = texture2D(uEnv, envUv(R), 2.0 + uLook.w * 5.0 + (boxed ? 3.0 * (1.0 - inWin) : 0.0)).rgb;   // never mirror-sharp
    vec3 L = normalize(drift(vec3(-0.45, 0.6, 0.75)));
    float spec = pow(max(dot(reflect(-L, N), V), 0.0), 36.0);
    float fres = 0.04 + 0.96 * pow(1.0 - NV, 5.0);
    if (uPass > 0.5) {
        // the plastic's own colour: a faint green-grey that deepens with thickness and at an angle,
        // strongest through the cut edges and the slab's rim
        float th = vFace > 5.5 ? 1.2 : (vFace > 1.5 && vFace < 3.5 ? max(uSize.x, uSize.y) * 0.08
                                                                    : mix(uThick.x, uThick.y, max(onRimB, onRail)));
        float len = th / max(NV, 0.22);
        // acrylic tints green-grey with thickness; a slab's clear plastic stays neutral
        vec3 absorb = pow(uBox.x > 0.0 ? vec3(0.972) : vec3(0.94, 0.975, 0.965), vec3(len));
        gl_FragColor = vec4(absorb, 1.0);
        return;
    }
    if (vFace > 6.5) {                       // the inner frame's cut edges: frosted, catching light
        vec3 c = mix(vec3(0.92, 0.95, 0.94), room, 0.35) * (0.7 + 0.5 * spec) + spec * 0.5;
        gl_FragColor = vec4(c * uExposure, 0.42);
        return;
    }
    if (vFace > 5.5) {                       // the inner frame's faces: clear, a touch of sheen
        float r6 = uLook.y * 0.6 * (0.2 + 0.8 * fres);
        vec3 c = room * 1.3 * r6 + vec3(spec) * 0.7;
        float hz = uHaze * 0.06 * (0.7 + 0.6 * vnoise(pm * 0.4));
        c += vec3(0.85, 0.87, 0.86) * hz;
        float a = clamp(0.03 + r6 * dot(room, vec3(0.33)) * 1.4 + spec * 0.6 + hz, 0.0, 0.8);
        gl_FragColor = vec4(c / max(a, 0.05) * uExposure, a);
        return;
    }
    if (vFace > 3.5) {                       // the label: printed stock, lit softly
        vec4 t = texture2D(uLabel, vUv);
        if (behind) {                        // the back of the label: plain stock inside its border
            vec2 e = min(vUv, 1.0 - vUv) * vec2(1400.0, 400.0);
            t = vec4(mix(vec3(0.11), vec3(0.957, 0.953, 0.933), step(24.0, min(e.x, e.y))), 1.0);
        }
        float d = 0.78 + 0.22 * max(dot(N, L), 0.0);
        gl_FragColor = vec4(t.rgb * d * uExposure, 1.0);
        return;
    }
    if (vFace > 1.5) {                       // the cut edge of thick acrylic: bright, a little green
        vec3 c = mix(uTint * (uBox.x > 0.0 ? vec3(0.93) : vec3(0.86, 0.95, 0.92)), room, 0.5) * (0.6 + 0.6 * spec) + spec * 0.4;
        gl_FragColor = vec4(c * uExposure, uLook.z);
        return;
    }
    float refl = uLook.y * (0.25 + 0.75 * fres);
    // the surface is never perfect: a fine orange peel that breaks up highlights
    float peel = hashc(floor(pm * 6.0)) * 0.5 + hashc(floor(pm * 2.3) + 7.0) * 0.5;
    spec *= 0.75 + 0.5 * peel;
    // polished outside edge: light runs along it inside the plastic
    float rimLine = (1.0 - smoothstep(0.0, 0.7, edgeD)) * step(0.01, uThick.x);
    float mould = rimLine * 0.6;
    if (boxed) {
        // a moulded slab: a thick rim with a step down to the window, a well for the label and a well
        // for the card, each edge a fine line that catches the light
        float rim = outerD;
        float step_ = (1.0 - smoothstep(0.0, 0.6, abs(rim - uBox.w))) * 0.55;   // a soft highlight on the slope's top
        float onRim = 1.0 - smoothstep(uBox.w - 0.2, uBox.w + 0.2, rim);
        float lip = 1.0 - smoothstep(0.0, 0.35, abs(dW));                 // the window's top edge
        // the line across under the label window that parts it from the card's space
        float divY = uWells.x - uWells.y * 0.5 - 0.6 - uBox.z;
        float divider = (1.0 - smoothstep(0.0, 0.4, abs(pm.y - divY))) * step(abs(pm.x), uSize.x * 0.5 - uBox.w);
        mould += step_ * 0.9 + lip * 0.6 + divider * 0.7 + (tilt > 0.0 ? 0.25 * tilt : 0.0);
        // the rim is thicker plastic and reflects more; the thin window over the card stays clear
        refl *= 1.0 + onRim * 0.8 - (1.0 - onRim) * 0.25;
    }
    if (uRails.w > 0.0) {                     // the rails: thicker, a touch more reflective, a lavender-blue cast
        refl *= 1.0 + onRail * 0.45;
        mould += seam * 1.3;
    }
    vec3 c = room * 1.4 * refl + vec3(spec) * 0.9 + uTint * uLook.w * 0.25 + mould * (0.35 + 0.65 * room);
    float a = uLook.x + refl * dot(room, vec3(0.33)) * 1.5 + spec * 0.8 + uLook.w * 0.12 + mould * 0.35;
    c += vec3(0.60, 0.64, 0.95) * onRail * 0.30 * uRails.w;
    a += onRail * 0.14 * uRails.w;
    // moulded plastic is not optical glass: a soft milky veil, uneven in a slow mottle, thicker at the rim,
    // lit by the room
    float haze = uHaze * mix(0.075, 0.14, onRimB) * (0.7 + 0.6 * vnoise(pm * 0.32)) * (0.8 + 0.6 * fres) * frost;
    c += mix(boxed ? vec3(0.88) : vec3(0.84, 0.86, 0.855), room, 0.35) * haze * (0.55 + 0.7 * dot(room, vec3(0.33)));
    a += haze;
    // the foot of each window's slope sits in a little shadow
    float foot = boxed && vFace < 1.5 ? 1.0 - smoothstep(0.0, 0.6, abs(dW + bevelW)) : 0.0;
    a += foot * 0.16;
    a = clamp(a, 0.0, 0.92);
    gl_FragColor = vec4(c / max(a, 0.05) * uExposure, a);
}
void main() {
    if (uFloor.x > 0.5 && vPosV.y > uFloor.y) discard;
    shade();
    if (uFloor.x > 0.5) {
        float d = clamp((uFloor.y - vPosV.y) / uFloor.z, 0.0, 1.0);
        gl_FragColor.a *= uFloor.w * (1.0 - d) * (1.0 - d);
    }
}
"""

MM = CARD_H / 88.0                  # one millimetre in scene units

# name: label, outer width, height, depth (mm), corner radius, where the card's centre sits from the
# holder's centre (mm, up), tint, look (base alpha, reflection, edge alpha, frost), label height (mm)
HOLDERS = {
    # a fitted sleeve: thin film cut close to the card, 64 x 89 mm with square-cut corners, the card resting at
    # its bottom with a millimetre spare at the top; small enough to sit inside a PSA slab's 64.5 x 90 mm space
    "sleeve": dict(label="Fitted sleeve", w=64.0, h=89.0, d=0.4, r=0.3, card_y=-0.5, tint=(1.0, 1.0, 1.0),
                   look=(0.02, 0.55, 0.06, 0.25), label_h=0.0, label_top=0.0, thick=(0.06, 0.06), haze=0.3),
    # a standard 35 pt top loader: 3 x 4 in outside with its corners cut off at 45 degrees, a pocket for
    # a 35 pt (0.89 mm) card between two 0.45 mm walls, so 1.8 mm in all; the card rests at the bottom
    "toploader": dict(label="Top loader", w=76.2, h=101.6, d=1.8, r=1.6, chamfer=4.5, card_y=-4.05,
                      tint=(0.94, 0.97, 1.0),
                      look=(0.02, 0.55, 0.45, 0.0), label_h=0.0, label_top=0.0, thick=(0.55, 1.8), bevel=0.35, haze=0.7,
                      # welded down the left, right and bottom: rails about 2.4 mm wide at the sides and 2.7 at
                      # the bottom, a hairline seam half a millimetre in at the open top
                      rails=(2.4, 2.7, 0.6, 1.0)),
    # a PSA slab to its published size: 80 x 135 mm and 9.05 mm deep, a rounded rim, a label window (PSA's
    # is 68 x 30 mm; drawn 64 x 27 so its bevel clears the rim's slope, with the label inside it)
    # at the top over a line that parts it from the card's space below, which is one open window with no
    # well of its own; four clear bars hold the card in place round PSA's 64.5 x 90 mm space, which the
    # fitted sleeve (64 x 89) sits inside with nothing overlapping
    "slab": dict(label="Graded slab", w=80.0, h=135.0, d=9.05, r=4.0, bevel=1.4, card_y=-16.25,
                 tint=(0.98, 0.98, 0.98), look=(0.015, 0.5, 0.6, 0.0), label_w=60.0, label_h=22.0,
                 win_w=64.0, win_h=27.0, label_top=6.0, rim=3.0, thick=(1.6, 9.05), haze=1.0,
                 bars=dict(space=(64.5, 90.0), w=1.6, d=2.4, h_len=52.0, v_len=78.0), divider=2.0),
}
# the slab's two moulded halves, for putting a card in one: the back holds the clear inner frame the card
# sits in, the front carries the label; each half the slab's depth, closed they make the whole slab
# each half stops 0.3 mm short of the middle, so the sleeved card (0.5 mm, centred) sits in the pocket
# between them and never shows through a half's inner face; their outer faces are the whole slab's
_HALF_D = HOLDERS["slab"]["d"] / 2 - 0.3
HOLDERS["slab_back"] = dict(HOLDERS["slab"], label="Slab, back half", d=_HALF_D, thick=(1.6, _HALF_D), label_h=0.0)
HOLDERS["slab_front"] = dict(HOLDERS["slab"], label="Slab, front half", d=_HALF_D, thick=(1.6, _HALF_D),
                             insert=None, bars=None)
SLAB_HALF_Z = 0.3 + _HALF_D / 2      # each half's centre from the card's, closed (mm)
HOLDERS["slab_back"]["inner_z"] = SLAB_HALF_Z        # the inner frame at the card, not in the half's middle
# each half moulds only its outer face (the rim, its step, the label and card windows): the front half its
# front, the back half its back; the faces where the halves meet stay plain, so no second bevel shows through
HOLDERS["slab_front"]["mould_face"] = 0
HOLDERS["slab_back"]["mould_face"] = 1
HOLDERS["slab_front"]["inner_z"] = -SLAB_HALF_Z      # the label where the whole slab has it
SLAB_ON = 16.25                      # the slab's centre above the card's when the card sits in it



def _rrect(hw, hh, r, n_corner):
    """A rounded rectangle's outline, counter-clockwise, with each point's outward normal."""
    r = max(0.0, min(r, hw, hh))
    out = []
    for cx, cy, a0 in ((hw - r, hh - r, 0), (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180), (hw - r, -hh + r, 270)):
        for k in range(n_corner + 1):
            a = math.radians(a0 + 90 * k / n_corner)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a), math.cos(a), math.sin(a)))
    return out


def _chamfer(hw, hh, c):
    """A rectangle with its corners cut off at 45 degrees, counter-clockwise; each side carries its own
    normal (its corner points are doubled), so the cuts read as crisp flats."""
    c = max(0.0, min(c, hw, hh))
    k = math.sqrt(0.5)
    corners = [((hw, hh - c), (hw - c, hh), (k, k)), ((-hw + c, hh), (-hw, hh - c), (-k, k)),
               ((-hw, -hh + c), (-hw + c, -hh), (-k, -k)), ((hw - c, -hh), (hw, -hh + c), (k, -k))]
    sides = [(0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0)]       # the side after each corner
    out = []
    for (a, b, n), sn in zip(corners, sides):
        out += [(a[0], a[1], *n), (b[0], b[1], *n), (b[0], b[1], *sn)]
        nxt = corners[(corners.index((a, b, n)) + 1) % 4][0]
        out.append((nxt[0], nxt[1], *sn))
    return out


def build_box(w, h, d, r, bevel=0.0, n_corner=8, segs=5, cy=0.0, faces=(0, 1, 2), uv_wh=None, chamfer=0.0):
    """A rounded box centred on (0, cy): front and back faces, and an edge that is rounded over by bevel
    (a quarter circle into each face) rather than cut square. uv runs across uv_wh (default the box)."""
    uw, uh = uv_wh or (w, h)
    bevel = max(0.0, min(bevel, d / 2 * 0.98, r * 0.98))
    t = d / 2
    # rings from the front face round the edge to the back face: (inset, z, normal xy weight, normal z)
    rings = []
    if bevel > 0:
        for k in range(segs + 1):
            th = math.pi / 2 * k / segs
            rings.append((bevel * (1 - math.sin(th)), t - bevel + bevel * math.cos(th), math.sin(th), math.cos(th)))
        for k in range(segs + 1):
            th = math.pi / 2 * k / segs
            rings.append((bevel * (1 - math.cos(th)), -t + bevel - bevel * math.sin(th), math.cos(th), -math.sin(th)))
    else:
        rings = [(0.0, t, 1.0, 0.0), (0.0, -t, 1.0, 0.0)]
    if chamfer > 0:
        outs = [_chamfer(w / 2 - inset, h / 2 - inset, chamfer - inset * 0.414) for inset, _z, _a, _b in rings]
    else:
        outs = [_rrect(w / 2 - inset, h / 2 - inset, r - inset, n_corner) for inset, _z, _a, _b in rings]
    v = []
    front, back = outs[0], outs[-1]
    fz, bz = rings[0][1], rings[-1][1]
    n = len(front)
    ff, fb, fe = faces

    def uv(x, y):
        return x / uw + 0.5, (y) / uh + 0.5
    for i in range(n):
        j = (i + 1) % n
        for (x, y, _a, _b) in ((0, 0, 0, 0), front[i], front[j]):
            v += [x, y + cy, fz, 0, 0, 1, *uv(x, y), ff]
        for (x, y, _a, _b) in ((0, 0, 0, 0), back[j], back[i]):
            v += [x, y + cy, bz, 0, 0, -1, *uv(x, y), fb]
    for k in range(len(rings) - 1):
        ra, rb = outs[k], outs[k + 1]
        (_, za, sa, ca), (_, zb, sb, cb) = rings[k], rings[k + 1]
        if abs(za - zb) < 1e-9 and ra[0][:2] == rb[0][:2]:
            continue
        for i in range(n):
            j = (i + 1) % n
            quad = [(ra[i], za, sa, ca), (rb[i], zb, sb, cb), (rb[j], zb, sb, cb),
                    (ra[i], za, sa, ca), (rb[j], zb, sb, cb), (ra[j], za, sa, ca)]
            for (x, y, nx, ny), z, s_, c_ in quad:
                v += [x, y + cy, z, nx * s_, ny * s_, c_, *uv(x, y), fe]
    return v


def _label_aspect():
    hd = HOLDERS["slab"]
    return hd["label_w"] / hd["label_h"]


def build_ring(ow, oh, orad, iw, ih, irad, d, cy, uv_wh, n_corner=8):
    """A flat frame (an outline with a hole), centred on (0, cy): the clear piece inside a slab that
    holds the card. Its faces are 6, its edges 7."""
    t = d / 2
    out_, in_ = _rrect(ow / 2, oh / 2, orad, n_corner), _rrect(iw / 2, ih / 2, irad, n_corner)
    uw, uh = uv_wh
    v = []
    n = len(out_)

    def uv(x, y):
        return x / uw + 0.5, (y + cy) / uh + 0.5
    for i in range(n):
        j = (i + 1) % n
        a, b, c, e = out_[i], out_[j], in_[j], in_[i]
        for z, nz in ((t, 1), (-t, -1)):
            tris = ((a, b, c), (a, c, e)) if nz > 0 else ((a, c, b), (a, e, c))
            for tri in tris:
                for (x, y, _nx, _ny) in tri:
                    v += [x, y + cy, z, 0, 0, nz, *uv(x, y), 6]
        for ring, sign in ((out_, 1), (in_, -1)):            # the outside and the hole's cut edges
            p0, p1 = ring[i], ring[j]
            for (p, z) in ((p0, t), (p0, -t), (p1, -t), (p0, t), (p1, -t), (p1, t)):
                v += [p[0], p[1] + cy, z, p[2] * sign, p[3] * sign, 0, *uv(p[0], p[1]), 7]
    return v


def build_holder(name):
    """The holder's mesh: the label first (opaque), then the clear pieces inside, then the shell.
    Returns (array, label vertex count)."""
    hd = HOLDERS[name]
    w, h, d, r = hd["w"] * MM, hd["h"] * MM, hd["d"] * MM, hd["r"] * MM
    v = []
    if hd["label_h"]:
        lw, lh = hd["label_w"] * MM, hd["label_h"] * MM
        # centred in its window (label_top is the window's top), with a margin all round
        cy = h / 2 - hd["label_top"] * MM - hd.get("win_h", hd["label_h"]) * MM / 2
        quad = [(-lw / 2, cy - lh / 2), (lw / 2, cy - lh / 2), (lw / 2, cy + lh / 2), (-lw / 2, cy + lh / 2)]
        for a, b, c in ((0, 1, 2), (0, 2, 3)):              # one label sheet inside, seen from both sides
            for k in (a, b, c):
                x, y = quad[k]
                v += [x, y, 0.0, 0, 0, 1, (x + lw / 2) / lw, (y - cy + lh / 2) / lh, 4]
    nl = len(v) // 9
    if hd.get("bars"):
        # the four clear bars that hold the card: top and bottom across it, left and right down it
        br = hd["bars"]
        sw, sh = br["space"][0] * MM, br["space"][1] * MM
        bw, bd = br["w"] * MM, br["d"] * MM
        cyc = (hd["card_y"] + SLEEVE_ON) * MM
        for bx, by, bl, bh in ((0.0, cyc + sh / 2 + bw / 2, br["h_len"] * MM, bw),
                               (0.0, cyc - sh / 2 - bw / 2, br["h_len"] * MM, bw),
                               (-sw / 2 - bw / 2, cyc, bw, br["v_len"] * MM),
                               (sw / 2 + bw / 2, cyc, bw, br["v_len"] * MM)):
            part = build_box(bl, bh, bd, 0.3 * MM, cy=by, faces=(6, 6, 7), uv_wh=(w, h))
            for q in range(0, len(part), 9):
                part[q] += bx
            v += part
    if hd.get("insert"):
        # the clear inner frame that holds the card, and the one round the label
        ins = hd["insert"]
        # sized to the sleeve the card wears in a slab, centred on it
        cyc = (hd["card_y"] + SLEEVE_ON) * MM
        sw, sh = HOLDERS["sleeve"]["w"] * MM, HOLDERS["sleeve"]["h"] * MM
        v += build_ring(sw + 2 * ins["side"] * MM, sh + 2 * ins["side"] * MM, 0.8 * MM + ins["side"] * MM,
                        sw + 0.5 * MM, sh + 0.5 * MM, 1.05 * MM, ins["d"] * MM, cyc, (w, h))
        if hd["label_h"]:
            lw, lh = hd["label_w"] * MM, hd["label_h"] * MM
            cyl = h / 2 - hd["label_top"] * MM - lh / 2
            v += build_ring(lw + 2 * ins["side"] * MM, lh + 2 * ins["side"] * MM, 1.5 * MM,
                            lw + 0.5 * MM, lh + 0.5 * MM, 0.4 * MM, ins["d"] * MM, cyl, (w, h))
    zi = hd.get("inner_z", 0.0) * MM
    if zi and v:                       # a slab half: its label and inner frame sit where the whole slab's do
        for k in range(2, len(v), 9):
            v[k] += zi
    v += build_box(w, h, d, r, bevel=hd.get("bevel", 0.0) * MM, chamfer=hd.get("chamfer", 0.0) * MM)
    return np.array(v, np.float32), nl


def slab_label(top="", name="", number="", condition="", aspect=3.0):
    """The slab's printed label, laid out the way a graded card's label reads: the year, game and set
    on the first line, the card's name large, its number and variety under it, and on the right the
    condition when one is given. No number grade, no grading company's marks: a plain house design."""
    from PySide6.QtGui import QPainter, QColor, QFont, QPen
    H = 420
    W = int(H * aspect)
    ink, stock = QColor("#1B1B1E"), QColor("#F5F4EF")
    img = QImage(W, H, QImage.Format_RGBA8888)
    img.fill(stock)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setPen(QPen(ink, 5))
    p.drawRect(14, 14, W - 28, H - 28)
    p.setPen(QPen(ink, 2))
    p.drawRect(30, 30, W - 60, H - 60)
    right = W - 70
    if condition:
        cx = W - 330
        p.drawLine(cx, 70, cx, H - 70)
        box = W - cx - 70
        size = 46
        while size > 20:                      # the longest word has to fit across the column
            f = QFont("Geist", size)
            f.setWeight(QFont.Bold)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
            p.setFont(f)
            if max(p.fontMetrics().horizontalAdvance(wd) for wd in condition.upper().split()) <= box:
                break
            size -= 2
        p.setPen(ink)
        p.drawText(cx + 20, 60, box, H - 120, Qt.AlignCenter | Qt.TextWordWrap, condition.upper())
        right = cx - 30
    p.setPen(ink)

    def line(text, y, hgt, size, weight, spacing=1.5, mono=False):
        lo = int(size * 0.62)
        while True:                            # smaller type before cutting a long line short
            f = QFont("Geist Mono" if mono else "Geist", size)
            f.setWeight(weight)
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
            p.setFont(f)
            if size <= lo or p.fontMetrics().horizontalAdvance(text.upper()) <= right - 70:
                break
            size -= 2
        p.drawText(70, y, right - 70, hgt, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(text.upper(), Qt.ElideRight, right - 70))
    line(top, 70, 76, 31, QFont.DemiBold, 2)
    line(name, 142, 118, 62, QFont.Bold, 1.5)
    line(number, 258, 76, 33, QFont.Medium, 2, mono=True)
    p.end()
    return img


# camera depth of field, a pass over the finished frame: each pixel's distance comes from where its
# ray meets the card's plane, focus sits on the card's centre, and the blur grows with how far in
# front of or behind that a point is, so a turned card goes soft toward its near and far edges
POST_VERT = """
#version 120
attribute vec2 aXY;
varying vec2 vUv;
void main() {
    vUv = aXY * 0.5 + 0.5;
    gl_Position = vec4(aXY, 0.0, 1.0);
}
"""

BGP_FRAG = """
#version 120
uniform sampler2D uImg;
uniform vec2 uScale;
varying vec2 vUv;
void main() {
    gl_FragColor = vec4(texture2D(uImg, (vUv - 0.5) * uScale + 0.5).rgb, 1.0);
}
"""


# ---------------------------------------------------------------- animated backdrops and entrances
# Backdrops after the 21st.dev shader pieces Anthony picked: Rings is the well-known concentric
# ripple with its colour channels a hair apart; Lines and Aurora are written for CardCrop in the same
# spirit. Each takes the frame's own time, so a video renders the same every time.
FX_BG = {
    "rings": ("Rings", """
#version 120
uniform vec2 uRes; uniform float uT; uniform vec3 uTint; varying vec2 vUv;
float ch(vec2 uv, float t, float j) {
    float c = 0.0;
    for (int i = 0; i < 5; i++) {
        float fi = float(i);
        c += 0.002 * fi * fi / abs(fract(t - 0.01 * j + fi * 0.01) * 5.0 - length(uv) + mod(uv.x + uv.y, 0.2));
    }
    return c;
}
void main() {
    vec2 uv = (vUv * uRes * 2.0 - uRes) / min(uRes.x, uRes.y);
    float t = uT * 0.05;
    vec3 c = vec3(ch(uv, t, 0.0), ch(uv, t, 1.0), ch(uv, t, 2.0));
    gl_FragColor = vec4(min(c, vec3(1.0)) * 0.5 + uTint * 0.2, 1.0);
}
"""),
    "lines": ("Lines", """
#version 120
uniform vec2 uRes; uniform float uT; uniform vec3 uTint; varying vec2 vUv;
float h1(float n) { return fract(sin(n * 12.9898) * 43758.5453); }
void main() {
    vec2 uv = vUv * uRes / min(uRes.x, uRes.y);
    float cols = 18.0;
    float cx = floor(uv.x * cols);
    float sp = h1(cx);
    float fx = fract(uv.x * cols);
    float y = fract(uv.y * 0.55 - uT * (0.08 + 0.32 * sp) + sp);
    float streak = smoothstep(0.0, 0.015, y) * pow(1.0 - y, 6.0);
    float lane = smoothstep(0.0, 0.12, fx) * smoothstep(1.0, 0.88, fx);
    vec3 hue = 0.55 + 0.45 * cos(6.28318 * (sp + vec3(0.0, 0.33, 0.67)) + uT * 0.25);
    float grid = step(0.94, fract(uv.y * 12.0)) * 0.05;
    vec3 col = uTint * 0.35 + hue * streak * lane * 0.85 + grid * hue;
    gl_FragColor = vec4(col, 1.0);
}
"""),
    "aurora": ("Aurora", """
#version 120
uniform vec2 uRes; uniform float uT; uniform vec3 uTint; varying vec2 vUv;
void main() {
    vec2 uv = (vUv * uRes * 2.0 - uRes) / min(uRes.x, uRes.y);
    float t = uT * 0.18;
    vec2 p = uv;
    for (int i = 1; i < 6; i++) {
        float fi = float(i);
        p += vec2(0.55 / fi * sin(fi * p.y + t + 0.3 * fi), 0.45 / fi * cos(fi * p.x + t * 1.3 + 0.7 * fi));
    }
    vec3 col = 0.5 + 0.5 * cos(vec3(0.0, 2.1, 4.2) + p.x * 1.4 + p.y * 0.9 + t);
    col = mix(uTint, col, 0.55) * (0.55 + 0.25 * sin(p.y * 2.0 + t));
    gl_FragColor = vec4(col * (1.0 - 0.35 * length(uv) * 0.5), 1.0);
}
"""),
}

# Entrances drawn over the finished frame for the first seconds of a video: a ring reveal (the
# backdrop's rings fill the frame and open from the centre onto the card), a holo sweep (a band of
# foil colour crossing the frame), and a lock-on (crosshair lines and corner brackets that close
# in on the card, after the React Bits crosshair).
FX_REVEAL = {"ring": ("Ring reveal", 1.6), "holo": ("Holo sweep", 1.4), "lock": ("Lock-on", 1.8)}
FX_REVEAL_FRAG = """
#version 120
uniform vec2 uRes; uniform float uT; uniform float uP; uniform int uKind; uniform vec2 uCard;
uniform vec3 uInk; varying vec2 vUv;
float ch(vec2 uv, float t, float j) {
    float c = 0.0;
    for (int i = 0; i < 5; i++) {
        float fi = float(i);
        c += 0.002 * fi * fi / abs(fract(t - 0.01 * j + fi * 0.01) * 5.0 - length(uv) + mod(uv.x + uv.y, 0.2));
    }
    return c;
}
float box(vec2 q, vec2 b) { vec2 d = abs(q) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
void main() {
    vec2 px = vUv * uRes;
    vec2 uv = (px * 2.0 - uRes) / min(uRes.x, uRes.y);
    float e = smoothstep(0.0, 1.0, uP);
    if (uKind == 0) {                                    // ring reveal
        float r = e * 2.4;
        float d = length(uv);
        vec3 c = min(vec3(ch(uv, uT * 0.05, 0.0), ch(uv, uT * 0.05, 1.0), ch(uv, uT * 0.05, 2.0)), vec3(1.0));
        float cover = smoothstep(r - 0.12, r, d);
        float edge = exp(-pow((d - r) * 18.0, 2.0)) * (1.0 - e);
        gl_FragColor = vec4(c * cover + vec3(edge), max(cover, edge));
    } else if (uKind == 1) {                             // holo sweep
        float x = (vUv.x + vUv.y * 0.6) * 0.62 - (e * 1.8 - 0.4);
        float band = exp(-x * x * 90.0);
        vec3 hue = 0.5 + 0.5 * cos(6.28318 * (vUv.x * 1.4 + vUv.y + uT * 0.4 + vec3(0.0, 0.33, 0.67)));
        gl_FragColor = vec4(hue * band, band * 0.85);
    } else {                                             // lock-on
        vec2 hb = uCard * mix(2.4, 1.0, e);
        float lw = 2.6 / min(uRes.x, uRes.y);
        vec2 q = uv;
        float frame = abs(box(q, hb));
        vec2 a = abs(q);
        float corner = step(hb.x * 0.62, a.x) * step(hb.y * 0.72, a.y);
        float bracket = (1.0 - smoothstep(lw * 1.2, lw * 2.4, frame)) * corner;
        float cross = (1.0 - smoothstep(lw * 0.4, lw * 1.4, abs(q.x))) + (1.0 - smoothstep(lw * 0.4, lw * 1.4, abs(q.y)));
        float fade = 1.0 - smoothstep(0.75, 1.0, uP);
        float a1 = clamp(bracket + cross * 0.45, 0.0, 1.0) * fade;
        float tick = step(0.98, fract(q.x * 10.0)) * (1.0 - smoothstep(lw, lw * 6.0, abs(q.y))) * 0.6 * fade;
        gl_FragColor = vec4(uInk, clamp(a1 + tick, 0.0, 1.0));
    }
}
"""


def prepare_backdrop_photo(path_or_img, blur=0.5, dim=0.45, long_side=1920):
    """A photo made into a backdrop: scaled so its long side is long_side, blurred by blur (0 to 1,
    as a share of its size), darkened by dim (0 none, 1 black), and lightly dithered so the soft
    gradients do not band. Returns BGR uint8, or None when the photo cannot be read."""
    import cv2
    img = path_or_img
    if isinstance(img, str):
        img = cv2.imread(img, cv2.IMREAD_COLOR)
        if img is None:                                  # HEIC and the like: let Qt try
            q = QImage(path_or_img)
            if q.isNull():
                return None
            q = q.convertToFormat(QImage.Format_RGB888)
            a = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine())
            img = cv2.cvtColor(a[:, :q.width() * 3].reshape(q.height(), q.width(), 3), cv2.COLOR_RGB2BGR)
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    k = long_side / max(h, w)
    img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))),
                     interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    f = img.astype(np.float32)
    sigma = float(blur) * 0.035 * long_side
    if sigma > 0.3:
        f = cv2.GaussianBlur(f, (0, 0), sigma)
    f *= 1.0 - 0.9 * float(min(max(dim, 0.0), 1.0))
    f += np.random.default_rng(7).uniform(-0.5, 0.5, f.shape).astype(np.float32)
    return np.clip(f, 0, 255).astype(np.uint8)


POST_FRAG = """
#version 120
uniform sampler2D uImg;
uniform vec2 uPx;
uniform vec2 uTan;
uniform vec3 uC;
uniform vec3 uN;
uniform float uAmt;
uniform float uFocus;          // where focus sits: 0 the card's centre, + farther, - nearer (share of distance)
uniform float uBloom;
uniform float uVig;
uniform float uGrain;
uniform float uSeed;
uniform sampler2D uDepth;      // for a group: each pixel's distance, drawn in its own pass
uniform float uUseDepth;
uniform float uZf;
varying vec2 vUv;
float coc(vec2 uv) {              // blur radius as a fraction of the frame height
    float zf, z;
    if (uUseDepth > 0.5) {
        zf = uZf * (1.0 + uFocus);
        z = texture2D(uDepth, uv).r;
        if (z <= 0.01) z = zf * 4.0;       // nothing drawn there: far behind
    } else {
        vec3 d = vec3((uv * 2.0 - 1.0) * uTan, -1.0);
        float dn = dot(d, uN);
        zf = (uZf > 0.0 ? uZf : -uC.z) * (1.0 + uFocus);   // the point the camera is on, or the card's middle
        z = abs(dn) < 1e-4 ? zf * 4.0 : dot(uC, uN) / dn;
        if (z <= 0.0) z = zf * 4.0;
    }
    // a band around the focus stays sharp, as a real lens keeps a little depth in focus
    return min(0.02, uAmt * 0.25 * max(0.0, abs(z - zf) / z - 0.006));
}
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main() {
    float r = coc(vUv);
    vec4 base = texture2D(uImg, vUv, -8.0);
    vec4 col = base;
    if (uAmt > 0.0 && r / uPx.y >= 0.5) {
        vec4 acc = base;
        float wsum = 1.0;
        for (int i = 1; i < 48; i++) {
            float fi = float(i);
            float rr = sqrt(fi / 48.0) * r;
            float a = fi * 2.39996323;
            vec2 o = vec2(cos(a), sin(a)) * rr;
            vec2 uv = vUv + vec2(o.x * uPx.x / uPx.y, o.y);
            // a sharper neighbour only spills into this pixel as far as its own blur reaches
            float w = clamp((coc(uv) - rr) / uPx.y + 1.0, 0.0, 1.0);
            acc += texture2D(uImg, uv, -8.0) * w;
            wsum += w;
        }
        col = acc / wsum;
    }
    if (uBloom > 0.0) {
        // light spilling round the brightest parts, the foil's flashes above all: the bright parts
        // of ever smaller copies of the frame, added back softly
        vec3 b = vec3(0.0);
        float wt = 0.0;
        for (int l = 2; l <= 7; l++) {
            float fl = float(l);
            vec3 m = texture2D(uImg, vUv, fl).rgb;
            float lum = dot(m, vec3(0.299, 0.587, 0.114));
            float k = 0.6 + 0.2 * fl;
            b += m * smoothstep(0.55, 0.95, lum) * k;
            wt += k;
        }
        col.rgb += b / wt * uBloom * 1.6;
    }
    if (uVig > 0.0) {
        vec2 q = (vUv - 0.5) * vec2(uPx.y / uPx.x, 1.0);
        float rr = length(q) / length(vec2(0.5 * uPx.y / uPx.x, 0.5));
        col.rgb *= 1.0 - uVig * 0.55 * smoothstep(0.35, 1.05, rr);
    }
    if (uGrain > 0.0) {
        // fine film grain, strongest in the mid tones, fresh every frame
        float n = hash(floor(vUv / uPx) + uSeed) + hash(floor(vUv / uPx) * 1.7 + uSeed * 3.1) - 1.0;
        float lum = dot(col.rgb, vec3(0.299, 0.587, 0.114));
        col.rgb += n * uGrain * 0.06 * (0.35 + 2.6 * lum * (1.0 - lum));
    }
    gl_FragColor = vec4(clamp(col.rgb, 0.0, 1.0), base.a);
}
"""


def card_radius(*imgs) -> float:
    """The card's own corner radius, in card units, read from its straightened pictures: along each
    corner's diagonal, how far the background reaches in before the card starts (a circle of radius r
    leaves r(sqrt 2 - 1) of it). Most cards are cut to about 3 mm, the standard used when nothing is read;
    some (Carddass, older promos, stickers) are much rounder, and a standard corner on them showed the
    background as black slivers. Never less than the standard."""
    import engine
    fr = [engine.corner_frac(img) for img in imgs if img is not None and not isinstance(img, QImage)]
    fr = [f for f in fr if f > 0]
    if not fr:
        return RADIUS
    return min(max(RADIUS, max(fr) * CARD_W), CARD_W * 0.16)


def _outline(n_corner=10, r=None):
    """Rounded-rectangle outline, counter-clockwise, in card units centred on 0."""
    w, h, r = CARD_W / 2, CARD_H / 2, (RADIUS if r is None else r)
    pts = []
    for cx, cy, a0 in ((w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180), (w - r, -h + r, 270)):
        for k in range(n_corner + 1):
            a = math.radians(a0 + 90 * k / n_corner)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def build_mesh(radius=None):
    """pos(3) normal(3) uv(2) face(1) per vertex; front 0, back 1, edge 2."""
    pts = _outline(r=radius)
    t = THICK / 2
    v = []

    def uv_front(x, y):
        return x / CARD_W + 0.5, y / CARD_H + 0.5

    def uv_back(x, y):          # mirrored, so the back reads correctly once the card is turned over
        return -x / CARD_W + 0.5, y / CARD_H + 0.5

    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        # front fan
        for (x, y) in ((0, 0), (x0, y0), (x1, y1)):
            v += [x, y, t, 0, 0, 1, *uv_front(x, y), 0]
        # back fan, reversed winding
        for (x, y) in ((0, 0), (x1, y1), (x0, y0)):
            v += [x, y, -t, 0, 0, -1, *uv_back(x, y), 1]
        # edge strip
        ex, ey = y1 - y0, -(x1 - x0)
        ln = math.hypot(ex, ey) or 1.0
        nx, ny = ex / ln, ey / ln
        for (x, y, z) in ((x0, y0, t), (x0, y0, -t), (x1, y1, -t), (x0, y0, t), (x1, y1, -t), (x1, y1, t)):
            v += [x, y, z, nx, ny, 0, 0, 0, 2]
    return np.array(v, np.float32)


def _to_qimage(img) -> QImage:
    """numpy BGR (any depth) or QImage -> RGBA QImage, at most 2048 tall. None gives a
    plain grey card, shown until a real one is loaded."""
    if img is None:
        q = QImage(630, 880, QImage.Format_RGBA8888)
        q.fill(0xFF3A3A3F)
        return q
    if isinstance(img, QImage):
        q = img
    else:
        import cv2
        a = img
        if a.dtype != np.uint8:
            a = (np.clip(a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 1.0), 0, 1) * 255
                 ).astype(np.uint8) if a.dtype != np.float32 else (np.clip(a, 0, 1) * 255).astype(np.uint8)
        if a.ndim == 2:
            a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        rgb = cv2.cvtColor(a[..., :3], cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        q = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    if q.height() > 2048:
        q = q.scaledToHeight(2048, Qt.SmoothTransformation)
    return q.convertToFormat(QImage.Format_RGBA8888)


def ease_linear(t):
    return t


def ease_out(t):                    # quartic: fast start, long soft landing
    return 1 - (1 - t) ** 4


def ease_in_out(t):                 # cubic
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t, s=1.4):        # lands a touch past the mark and settles back
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


EASES = {"linear": ease_linear, "out": ease_out, "inout": ease_in_out, "back": ease_out_back}

REST = (0.0, 0.0)                   # face-on, square to the camera


def _nearest(cur, target):
    """target + k * 360 closest to cur, so a preset turns the short way round."""
    return target + 360 * round((cur - target) / 360)


# ---------------------------------------------------------------- turntable paths for video
def path_loop(t):
    """Steady turn that loops without a seam: start and end frames match."""
    return 360 * t, 6 + 3 * math.sin(2 * math.pi * t)


def path_eased(t):
    """Hold on the front, ease all the way round, settle on the front again."""
    hold = 0.12
    if t < hold or t > 1 - hold:
        u = 0.0 if t < hold else 1.0
    else:
        u = ease_in_out((t - hold) / (1 - 2 * hold))
    return 360 * u, 6 * (1 - 0.5 * math.sin(math.pi * u))


def path_showcase(t):
    """A slow sway either side so the foil plays, then a full eased turn."""
    if t < 0.36:
        u = t / 0.36
        env = math.sin(math.pi * u)
        return 28 * env * math.sin(2 * math.pi * u), 6 + 7 * env * math.cos(2 * math.pi * u)
    u = ease_in_out((t - 0.36) / 0.64)
    return 360 * u, 6 + 2 * math.sin(math.pi * u)


PATHS = {"loop": path_loop, "eased": path_eased, "showcase": path_showcase}


# ---------------------------------------------------------------- the room the card reflects
_STUDIO = None


def studio_env():
    """A photo studio as the card sees it: a dark room, a tall softbox on the left, a strip light on
    the right, a soft top light and a warm floor bounce. BGR, square."""
    global _STUDIO
    if _STUDIO is None:
        import cv2
        n = 512
        y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n
        img = np.zeros((n, n, 3), np.float32)
        img += (0.05 + 0.06 * (1 - y))[..., None] * np.array([1.0, 0.98, 0.95])        # the room
        img += (np.exp(-((y - 0.95) / 0.12) ** 2) * 0.22)[..., None] * np.array([0.55, 0.75, 1.0])  # floor bounce
        def box(x0, x1, y0, y1, c, soft=0.012):
            m = ((x > x0) & (x < x1) & (y > y0) & (y < y1)).astype(np.float32)
            m = cv2.GaussianBlur(m, (0, 0), soft * n)
            return m[..., None] * np.array(c, np.float32)
        img += box(0.14, 0.34, 0.12, 0.62, [1.0, 1.0, 1.0])           # the key softbox
        img += box(0.74, 0.80, 0.08, 0.80, [1.0, 0.96, 0.9], 0.008)     # a strip light
        img += box(0.40, 0.62, 0.02, 0.10, [0.85, 0.9, 1.0], 0.02)      # the top light
        _STUDIO = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    return _STUDIO


def prepare_env(path_or_img, size=768):
    """A photo made into the room the card reflects: the middle square, lightly softened."""
    import cv2
    img = prepare_backdrop_photo(path_or_img, blur=0.03, dim=0.0, long_side=size * 4 // 3)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = min(h, w)
    img = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def _qimage_to_float(q):
    q = q.convertToFormat(QImage.Format_RGBA64)
    a = np.frombuffer(q.constBits(), np.uint16).reshape(q.height(), q.bytesPerLine() // 2)[:, :q.width() * 4]
    return a.reshape(q.height(), q.width(), 4).astype(np.float32)


def _float_to_qimage(a):
    a = np.ascontiguousarray(np.clip(a + 0.5, 0, 65535).astype(np.uint16))
    h, w = a.shape[:2]
    return QImage(a.data, w, h, w * 8, QImage.Format_RGBA64).copy()


# ---------------------------------------------------------------- camera moves
# each takes u from 0 to 1 and gives the camera: zoom (1 frames the whole card), px and py (the point
# on the card it looks at, -1 to 1 across and up), and, for the tours, the card's yaw and pitch too

def _keys(keys, u):
    """Eased from key to key: keys are (time, dict) in time order."""
    if u <= keys[0][0]:
        return dict(keys[0][1])
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if u <= t1:
            e = ease_in_out((u - t0) / max(1e-6, t1 - t0))
            return {k: a.get(k, 0.0) + (b.get(k, 0.0) - a.get(k, 0.0)) * e for k in set(a) | set(b)}
    return dict(keys[-1][1])


def rack_focus(u):
    """The focus pull: from well behind the card onto it, quick then settling."""
    return 0.32 * (1 - ease_out(min(1.0, max(0.0, u))))


def cam_push_slow(u):
    return dict(zoom=1.0 + 0.55 * ease_in_out(u))


def cam_push_fast(u):
    return dict(zoom=1.0 + 1.1 * ease_out(min(1.0, u / 0.35)))


def cam_pull_back(u):
    return dict(zoom=2.1 - 1.1 * ease_out(min(1.0, u / 0.6)))


def cam_breathe(u):
    return dict(zoom=1.0 + 0.35 * (0.5 - 0.5 * math.cos(2 * math.pi * u)))


_CORNERS = [(-0.62, 0.66), (0.62, 0.66), (0.62, -0.66), (-0.62, -0.66)]     # TL, TR, BR, BL


def _tour(side_yaw, t0, t1, keys):
    """Corner to corner on one side, each corner leaned toward a little so its foil and edge catch light."""
    seg = (t1 - t0) / 4
    for i, (cx, cy) in enumerate(_CORNERS):
        a = t0 + i * seg
        mx = -cx if side_yaw else cx                 # the back is seen mirrored
        pose = dict(zoom=2.7, px=cx, py=cy, yaw=side_yaw - 12 * mx, pitch=8 * cy)
        keys.append((a + seg * 0.35, pose))
        keys.append((a + seg * 0.85, dict(pose, yaw=pose["yaw"] + 4 * mx)))


def cam_corners_front(u):
    keys = [(0.0, dict(zoom=1.0, yaw=0, pitch=6)), (0.08, dict(zoom=1.0, yaw=0, pitch=6))]
    _tour(0, 0.08, 0.86, keys)
    keys.append((1.0, dict(zoom=1.0, yaw=0, pitch=6)))
    return _keys(keys, u)


def cam_corners_both(u):
    keys = [(0.0, dict(zoom=1.0, yaw=0, pitch=6))]
    _tour(0, 0.04, 0.44, keys)
    keys.append((0.50, dict(zoom=1.0, yaw=0, pitch=6)))
    keys.append((0.56, dict(zoom=1.0, yaw=180, pitch=6)))
    _tour(180, 0.56, 0.94, keys)
    keys.append((1.0, dict(zoom=1.0, yaw=180, pitch=6)))
    return _keys(keys, u)


def cam_pan_down(u):
    keys = [(0.0, dict(zoom=1.0, yaw=0, pitch=6)), (0.15, dict(zoom=2.2, py=0.62, yaw=-6, pitch=10)),
            (0.85, dict(zoom=2.2, py=-0.62, yaw=6, pitch=0)), (1.0, dict(zoom=1.0, yaw=0, pitch=6))]
    return _keys(keys, u)


def cam_edges(u):
    """Round the card's four edges, close, for the whitening buyers look for."""
    keys = [(0.0, dict(zoom=1.0, yaw=0, pitch=6))]
    pts = [(0.0, 0.86, 0, 14), (0.78, 0.0, -16, 0), (0.0, -0.86, 0, -14), (-0.78, 0.0, 16, 0)]
    for i, (x, y, yw, pt) in enumerate(pts):
        a = 0.06 + i * 0.21
        keys.append((a + 0.07, dict(zoom=2.4, px=x, py=y, yaw=yw, pitch=pt)))
        keys.append((a + 0.17, dict(zoom=2.4, px=x, py=y, yaw=yw * 0.7, pitch=pt * 0.7)))
    keys.append((1.0, dict(zoom=1.0, yaw=0, pitch=6)))
    return _keys(keys, u)


def cam_reel(u):
    """For Reels and TikTok: a sway so the foil plays and a full turn with a gentle push in, then close
    on each corner of the front, then back to the whole card."""
    if u < 0.42:
        y, p = path_showcase(u / 0.42)
        return dict(yaw=y, pitch=p, zoom=1.0 + 0.12 * math.sin(math.pi * u / 0.42))
    c = cam_corners_front((u - 0.42) / 0.58)
    return c


# ---- sleeving and top loading: the card stays the hero in the middle, the holders slide on and off it
# (from below, as a sleeve goes on, open end first). A rig lists the holders with their centres in mm
# above the card's centre, and the frame the camera keeps: its middle (mm, up), height and width (mm).
# where each sits when the card is all the way in: the fitted sleeve's centre half a millimetre above the
# card's, and the sleeved card resting on the top loader's welded bottom rail (2.7 mm), not in it:
# loader bottom 4.05 - 50.8 = -46.75, rail top -44.05, sleeve bottom -44.0
SLEEVE_ON, LOADER_ON = 0.5, 4.05
# off screen below the card while they wait: the shot is framed on the card alone
SLEEVE_OFF, LOADER_WAIT, LOADER_OFF = -165.0, -175.0, -300.0


def _rig(sleeve=None, loader=None):
    hs = []
    lo, hi = -44.0, 44.0
    if sleeve is not None:
        hs.append(("sleeve", sleeve))
        lo, hi = min(lo, sleeve - 44.5), max(hi, sleeve + 44.5)
    if loader is not None:
        hs.append(("toploader", loader))
        lo, hi = min(lo, max(loader - 50.8, -160.0)), max(hi, loader + 50.8)
    return hs, lo, hi


def _sleeve_keys(u, keys):
    """Eased between keys of (time, sleeve, loader, frame middle, frame height)."""
    for (t0, *a), (t1, *b) in zip(keys, keys[1:]):
        if u <= t1:
            e = ease_in_out(min(1.0, max(0.0, (u - t0) / max(1e-6, t1 - t0))))
            return [None if x is None else x + (y - x) * e for x, y in zip(a, b)], e, (t0, t1)
    return list(keys[-1][1:]), 1.0, (keys[-1][0], keys[-1][0])


def _sleeve_pose(vals, moving):
    s_, l_, cy, fh = vals
    hs, _lo, _hi = _rig(s_, l_)
    sway = 14.0 * math.sin(math.pi * moving)          # a quarter turn of interest while things slide
    # framed on the card alone: the sleeve and the top loader come in from off screen and never move the camera
    return dict(yaw=sway, pitch=7.0, rig=dict(holders=hs, frame=(0.0, 0.0, 0.0)))


def mv_sleeve(u):
    """Into a fitted sleeve."""
    keys = [(0.0, SLEEVE_OFF, None, -50.0, 214.0), (0.15, SLEEVE_OFF, None, -50.0, 214.0),
            (0.85, SLEEVE_ON, None, 1.0, 112.0), (1.0, SLEEVE_ON, None, 1.0, 112.0)]
    vals, e, (t0, t1) = _sleeve_keys(u, keys)
    return _sleeve_pose(vals, e if 0.15 <= u <= 0.85 else 0.0)


def mv_sleeve_load(u):
    """Into a fitted sleeve, then the sleeved card into a top loader."""
    keys = [(0.0, SLEEVE_OFF, LOADER_OFF, -50.0, 214.0), (0.08, SLEEVE_OFF, LOADER_OFF, -50.0, 214.0),
            (0.40, SLEEVE_ON, LOADER_OFF, -50.0, 214.0), (0.50, SLEEVE_ON, LOADER_WAIT, -52.0, 220.0),
            (0.88, SLEEVE_ON, LOADER_ON, 5.5, 122.0), (1.0, SLEEVE_ON, LOADER_ON, 5.5, 122.0)]
    vals, e, (t0, t1) = _sleeve_keys(u, keys)
    moving = e if (0.08 <= u <= 0.40 or 0.50 <= u <= 0.88) else 0.0
    return _sleeve_pose(vals, moving)


def mv_unload(u):
    """Out of the top loader, then out of the sleeve: the first one backwards."""
    return mv_sleeve_load(1.0 - u)


def mv_unsleeve(u):
    """Out of the sleeve."""
    return mv_sleeve(1.0 - u)


def mv_slab(u):
    """Into a slab, sleeved, the way one is made: the back half rises from below the frame and comes in
    behind the card; then the front half, label and all, rises from below in front of the card and
    closes onto the back, pressing home with a small give where the halves meet. Both halves start
    off screen below, so nothing appears out of thin air."""
    def ease(a, b):
        return ease_in_out(min(1.0, max(0.0, (u - a) / (b - a))))
    low = -260.0                                       # well below the frame, whatever it is framing
    back_dy = low + (SLAB_ON - low) * ease(0.06, 0.40)
    back_dz = -14.0 + (14.0 - SLAB_HALF_Z) * ease(0.36, 0.48)   # up behind the card, then in to touch it
    front_dy = low + (SLAB_ON - low) * ease(0.46, 0.80)
    # up in front, closed to a hair off the back, then pressed home: it never goes past closed, so the
    # card in its pocket between the halves never shows through
    front_dz = 14.0 - (14.0 - SLAB_HALF_Z - 0.12) * ease(0.76, 0.90) - 0.12 * ease(0.90, 0.97)
    hs = [("sleeve", SLEEVE_ON), ("slab_back", back_dy, back_dz), ("slab_front", front_dy, front_dz)]
    sway = 10.0 * math.sin(math.pi * ease(0.06, 0.90))
    return dict(yaw=sway, pitch=7.0, rig=dict(holders=hs, frame=(0.0, 0.0, 0.0)))


def mv_unslab(u):
    """Out of the slab: the same steps backwards."""
    return mv_slab(1.0 - u)


# name: the holder the card is in when the move ends
SLEEVE_ENDS = {"sleeve_in": "sleeve", "sleeve_load": "sleeve_tl", "unload": "", "unsleeve": "",
               "slab_in": "slab", "unslab": ""}


# name: (label, function, live seconds, whether it sets the card's angle too)
CAMERA_MOVES = {
    "push_slow": ("Slow push in", cam_push_slow, 5.0, False),
    "push_fast": ("Fast push in", cam_push_fast, 2.5, False),
    "pull_back": ("Pull back reveal", cam_pull_back, 3.0, False),
    "breathe": ("Breathe in and out", cam_breathe, 5.0, False),
    "corners": ("Corner tour, front", cam_corners_front, 9.0, True),
    "corners_both": ("Corner tour, both sides", cam_corners_both, 16.0, True),
    "edges": ("Edge tour, front", cam_edges, 9.0, True),
    "pan": ("Pan top to bottom", cam_pan_down, 6.0, True),
    "reel": ("Reel: sway, turn, corner tour", cam_reel, 15.0, True),
    "sleeve_in": ("Sleeve it", mv_sleeve, 4.0, True),
    "sleeve_load": ("Sleeve it, then top load", mv_sleeve_load, 7.5, True),
    "unload": ("Out of the top loader and sleeve", mv_unload, 7.5, True),
    "unsleeve": ("Out of the sleeve", mv_unsleeve, 4.0, True),
    "slab_in": ("Into a slab", mv_slab, 5.0, True),
    "unslab": ("Out of the slab", mv_unslab, 5.0, True),
}
OVERLAY_MOVES = ["push_slow", "push_fast", "pull_back", "breathe"]      # these ride on any motion
TOUR_MOVES = ["corners", "corners_both", "edges", "pan", "reel", "sleeve_in", "sleeve_load", "unload", "unsleeve",
              "slab_in", "unslab"]
SLEEVE_MOVES = list(SLEEVE_ENDS)                  # these are motions of their own


# ---------------------------------------------------------------- several cards at once
# a layout places card i of n at moment u (0 to 1, one seamless loop): x, y, z in card cells (a cell is a
# card, or its holder, with a little air), the card's own yaw, pitch and roll in degrees, and a lift for
# the one that is moving. Each layout also says how much room it needs, where its middle is, how the
# group is first turned to the camera, which card the lens focuses on, and how long one loop takes.

def _no_pass_through(pss, cw, ch, size, order_z=None):
    """Cards are solid: where two overlap face to face and one turns or tilts, the one behind is pushed
    back just far enough that the turning card clears it, instead of cutting through it. Order front to
    back comes from the layout when there is one, so a card never swaps sides of its neighbour."""
    n = len(pss)
    if n < 2:
        return
    w, h = size
    info = []
    for i, ps in enumerate(pss):
        r = QMatrix4x4()
        r.rotate(ps.get("roll", 0.0), 0, 0, 1)
        r.rotate(ps.get("pitch", 0.0), 1, 0, 0)
        r.rotate(ps.get("yaw", 0.0), 0, 1, 0)
        k = max(0.0, ps.get("scale", 1.0))
        pts = [r.map(QVector3D(sx * w / 2 * k, sy * h / 2 * k, 0)) for sx in (-1, 1) for sy in (-1, 1)]
        info.append((max(abs(q.x()) for q in pts), max(abs(q.y()) for q in pts), max(abs(q.z()) for q in pts)))
    key = order_z if order_z is not None else [p["z"] for p in pss]
    order = sorted(range(n), key=lambda i: (-key[i], i))
    gap = STACK_GAP * ch
    for a_, j in enumerate(order):
        zj = pss[j]["z"] * ch
        for i in order[:a_]:
            ox = info[i][0] + info[j][0] - abs(pss[i]["x"] * cw - pss[j]["x"] * cw)
            oy = info[i][1] + info[j][1] - abs(pss[i]["y"] * ch - pss[j]["y"] * ch)
            if ox <= 0 or oy <= 0:
                continue
            wgt = min(1.0, ox / (0.12 * h)) * min(1.0, oy / (0.12 * h))     # eases in as they meet, no jumps
            need = info[i][2] + info[j][2]
            if need < 1e-5:
                continue
            zj = min(zj, pss[i]["z"] * ch - (need + gap) * wgt)
        pss[j]["z"] = zj / ch


STACK_AIR = 1.2           # mm of air between stacked cards, so each layer reads and none ever touches
STACK_GAP = 0.07          # cells between stacked cards; the renderer sets it to the real thickness each frame


def _grid(n):
    cols = n if n <= 5 else math.ceil(n / 2)
    rows = math.ceil(n / cols)
    return cols, rows


def grp_stack(u, i, n):
    """Flip through a stack: the front card rises clear of the others, turns over while it travels
    above them to the back, then drops straight down into the back slot, again and again, a deck
    being looked through. Its lowest point stays above the top of the stack the whole time it is
    turning, so it never cuts through a card and nothing has to be pushed out of its way (the old
    path did, and the stack jumped back and forth to let it pass)."""
    step = u * n
    k = int(math.floor(step)) % n
    t = step - math.floor(step)
    r = (i - k) % n                                   # 0 is the front of the stack
    HH = 0.47                                         # half a card (or holder) in cells
    PEAK = 2 * HH + 0.06                              # high enough that, turned any way, it clears the top
    FWD = 0.10                                        # a little toward you first, off the face of the next
    back = -(n - 1) * STACK_GAP

    def rest(slot):                                   # squared up, each card exactly behind the one in front
        return dict(x=0.0, y=0.0, z=-slot * STACK_GAP, yaw=0.0, pitch=0.0, roll=0.0)
    if r == 0:
        if t < 0.22:                                  # up, still facing you
            a = ease_in_out(t / 0.22)
            return dict(x=0.0, y=PEAK * a, z=FWD * a, yaw=0.0, pitch=0.0, roll=0.0)
        if t < 0.72:                                  # over the top, turning, to above the back slot
            a = ease_in_out((t - 0.22) / 0.5)
            return dict(x=0.0, y=PEAK, z=FWD + (back - FWD) * a, yaw=0.0, pitch=-360.0 * a,
                        roll=-6.0 * math.sin(math.pi * a))
        a = ease_in_out((t - 0.72) / 0.28)            # straight down into the back
        return dict(x=0.0, y=PEAK * (1 - a), z=back, yaw=0.0, pitch=-360.0, roll=0.0)
    e = ease_in_out(min(1.0, max(0.0, (t - 0.22) / 0.48)))      # the rest step forward while it is up
    return rest(r - e)


def grp_carousel(u, i, n):
    """Round a circle: the cards stand on a ring facing out, and the ring turns."""
    r = max(0.95, n * 0.86 / (2 * math.pi))
    a = 2 * math.pi * (i / n + u)
    return dict(x=r * math.sin(a), y=0.0, z=r * math.cos(a) - r, yaw=math.degrees(a), pitch=0.0, roll=0.0)


def grp_fan(u, i, n):
    """A hand of cards: they fan open round a point below, hold, and close again."""
    if u < 0.3:
        e = ease_out_back(u / 0.3, 1.1)
    elif u < 0.7:
        e = 1.0
    else:
        e = 1 - ease_in_out((u - 0.7) / 0.3)
    spread = min(13.0, 70.0 / max(1, n - 1)) if n > 1 else 0.0
    ang = math.radians((i - (n - 1) / 2) * spread * e)
    R = 1.45
    x, z = R * math.sin(ang), i * STACK_GAP
    # while open, the whole hand turns a little to catch the light: one rigid turn of the fan, eased in
    # and out, so no card ever swings through its neighbour
    # The turn is given whole ("turn"), applied to the hand before each card's place in it: turning each
    # card and its position separately put the roll after the turn, so the cards stopped lying parallel,
    # and the nearer end of the hand jumped to the top of the pile and back with every sway.
    hold = (u - 0.3) / 0.4
    sway = 9.0 * math.sin(2 * math.pi * hold) * math.sin(math.pi * hold) if 0.0 < hold < 1.0 else 0.0
    return dict(x=x, y=R * math.cos(ang) - R, z=z, yaw=0.0, pitch=0.0, roll=-math.degrees(ang),
                turn=sway, layer=i)


def grp_wave(u, i, n):
    """A row (two for more than five), each card turning a full circle a beat after its neighbour."""
    cols, rows = _grid(n)
    c, rw = i % cols, i // cols
    x = (c - (cols - 1) / 2) * 1.0
    y = ((rows - 1) / 2 - rw) * 1.0
    start = (c / max(1, cols - 1)) * 0.45 + rw * 0.08 if cols > 1 else rw * 0.08
    e = ease_in_out(min(1.0, max(0.0, (u - start) / 0.42)))
    return dict(x=x, y=y + 0.05 * math.sin(math.pi * e), z=0.12 * math.sin(math.pi * e), yaw=360.0 * e,
                pitch=0.0, roll=0.0)


def grp_spread(u, i, n):
    """From a neat stack the cards slide out into a row (two for more than five), hold, and gather back."""
    if u < 0.3:
        e = ease_in_out(u / 0.3)
    elif u < 0.72:
        e = 1.0
    else:
        e = 1 - ease_in_out((u - 0.72) / 0.28)
    cols, rows = _grid(n)
    c, rw = i % cols, i // cols
    tx = (c - (cols - 1) / 2) * 1.0
    ty = ((rows - 1) / 2 - rw) * 1.0
    ri = n - 1 - i
    return dict(x=tx * e, y=ty * e, z=-ri * STACK_GAP * (1 - e), yaw=8.0 * math.sin(math.pi * e), pitch=0.0,
                roll=0.0)


def grp_lift(u, i, n):
    """Lift off the stack: from a neat stack the front card lifts up and out of the shot, then the next,
    until none are left; then they come back down onto the stack in turn, the same moves backwards."""
    t = u / 0.5 if u < 0.5 else (1.0 - u) / 0.5
    step = min(t * (n + 0.35), float(n))                 # a breath of the full stack at each end
    k = int(math.floor(step))
    e = ease_in_out(min(1.0, (step - k) / 0.85)) if k < n else 0.0
    gone = dict(x=0.0, y=3.4, z=0.6, yaw=0.0, pitch=-28.0, roll=0.0)
    if i < k:
        return gone
    if i == k:                                           # the one lifting off
        return dict(x=0.0, y=3.4 * e * e, z=0.6 * e, yaw=0.0, pitch=-28.0 * e, roll=0.0)
    slot = (i - k) - e                                   # the rest move up to the front, squared up
    return dict(x=0.0, y=0.0, z=-slot * STACK_GAP, yaw=0.0, pitch=0.0, roll=0.0)


def hash_unit(i):
    return (math.sin(i * 12.9898 + 4.1) * 43758.5453) % 1.0


def grp_meta(name, n):
    """(width, height of the room it needs, in cells; middle x, y; the camera's turn and tilt, always 0 so
    every group starts head on; seconds a loop;
    the lens's focus, in cells nearer than the middle)"""
    if name == "lift":
        return dict(w=1.3, h=1.4, cx=0.0, cy=0.0, yaw=0.0, pitch=0.0, secs=max(4.0, 2.2 * n), focus=0.0,
                    floor=-0.5 - 0.012 * n)
    if name == "stack":
        return dict(w=1.25, h=2.15, cx=0.0, cy=0.5, yaw=0.0, pitch=0.0, secs=max(4.0, 1.25 * n), focus=0.0,
                    floor=-0.5 - 0.012 * n)
    if name == "carousel":
        r = max(0.95, n * 0.86 / (2 * math.pi))
        return dict(w=2 * r + 1.0, h=1.25 + 0.35 * r, cx=0.0, cy=0.0, yaw=0.0, pitch=0.0, secs=max(8.0, 1.6 * n),
                    focus=0.0, floor=-0.5, focus_front=True)
    if name == "fan":
        spread = min(13.0, 70.0 / max(1, n - 1)) if n > 1 else 0.0
        a = math.radians((n - 1) / 2 * spread)
        return dict(w=2 * 1.45 * math.sin(a) + 1.15, h=1.5, cx=0.0, cy=0.1, yaw=0.0, pitch=0.0, secs=6.0,
                    focus=0.0, floor=-0.62)
    cols, rows = _grid(n)
    return dict(w=cols * 1.0 + 0.2, h=rows * 1.0 + 0.25, cx=0.0, cy=0.0, yaw=0.0, pitch=0.0,
                secs=(5.0 if name == "wave" else 7.0) + 0.2 * n, focus=0.0, floor=-0.5 - (rows - 1) / 2)


# name: (label, layout)
GROUP_PRESETS = {
    "stack": ("Flip through the stack", grp_stack),
    "carousel": ("Round a circle", grp_carousel),
    "fan": ("Fan out like a hand", grp_fan),
    "wave": ("Wave of turns", grp_wave),
    "spread": ("Spread out and gather", grp_spread),
    "lift": ("Lift off the stack", grp_lift),
}
GROUP_MAX = 12


# ---------------------------------------------------------------- entrances
# each takes u from 0 to 1 and gives offsets from the resting pose: yaw and pitch in degrees,
# roll in degrees, ox and oy in card heights (oy up), and scale; all end at nothing (0, 1)

def ease_out_bounce(t):
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def ease_out_elastic(t):
    if t <= 0 or t >= 1:
        return float(t >= 1)
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


def _rest(**k):
    out = dict(yaw=0.0, pitch=0.0, roll=0.0, ox=0.0, oy=0.0, scale=1.0)
    out.update(k)
    return out


def ent_drop(u):            # comes down into frame from above and settles just past the mark
    e = ease_out_back(u, 1.2)
    return _rest(oy=2.4 * (1 - e), pitch=-28 * (1 - ease_out(u)))


def ent_rise(u):            # rises up into frame and settles just past the mark
    e = ease_out_back(u, 1.2)
    return _rest(oy=-2.4 * (1 - e), pitch=28 * (1 - ease_out(u)))


def ent_slide_left(u):      # slides in from the left, turning to face you
    e = ease_out(u)
    return _rest(ox=-3.0 * (1 - e), yaw=-65 * (1 - ease_out_back(u, 1.0)), roll=-4 * (1 - e))


def ent_slide_right(u):     # from the right
    e = ease_out(u)
    return _rest(ox=3.0 * (1 - e), yaw=65 * (1 - ease_out_back(u, 1.0)), roll=4 * (1 - e))


def ent_flip(u):            # turns in from edge-on, a turn and a half, landing with a little give
    return _rest(yaw=-540 * (1 - ease_out_back(u, 1.1)), scale=0.75 + 0.25 * ease_out(u))


def ent_flip_vertical(u):   # tumbles in end over end
    return _rest(pitch=-540 * (1 - ease_out_back(u, 1.1)), scale=0.75 + 0.25 * ease_out(u))


def ent_spin_in(u):         # spirals in from far away
    e = ease_out(u)
    return _rest(scale=0.04 + 0.96 * e, yaw=720 * (1 - e), roll=-90 * (1 - e))


def ent_pop(u):             # pops up from nothing with a springy overshoot
    return _rest(scale=max(0.0, ease_out_elastic(u)), pitch=10 * (1 - ease_out(u)))


def ent_toss(u):            # tossed in from the left on an arc, spinning, and caught
    e = ease_out(u)
    return _rest(ox=-2.8 * (1 - e), oy=1.6 * math.sin(math.pi * min(1.0, u * 1.15)) * (1 - e),
                 yaw=-360 * (1 - e), roll=-25 * (1 - e))


ENTRANCES = {
    "drop": ("Drop in", ent_drop), "rise": ("Rise up", ent_rise),
    "slide_left": ("Slide in from the left", ent_slide_left), "slide_right": ("Slide in from the right", ent_slide_right),
    "flip": ("3D flip in", ent_flip), "tumble": ("Tumble in", ent_flip_vertical),
    "spin": ("Spiral in", ent_spin_in), "pop": ("Pop", ent_pop), "toss": ("Toss and catch", ent_toss),
}
ENTRANCE_SECONDS = 1.6

# outros are the entrances played backwards, named for where the card goes
_OUT = {"rise": "Drop out", "drop": "Lift off", "slide_left": "Slide out to the left",
        "slide_right": "Slide out to the right", "flip": "3D flip out", "tumble": "Tumble out",
        "spin": "Spiral away", "pop": "Pop out", "toss": "Toss away"}
OUTROS = {k: (label, (lambda u, f=ENTRANCES[k][1]: f(1.0 - u))) for k, label in _OUT.items()}


def _ease_in(t):
    return t ** 3


# the turning entrances never leave the frame, so their outros turn away and shrink to nothing
OUTROS["flip"] = ("3D flip out", lambda u: _rest(yaw=540 * _ease_in(u), scale=max(0.0, 1 - _ease_in(u))))
OUTROS["tumble"] = ("Tumble out", lambda u: _rest(pitch=540 * _ease_in(u), scale=max(0.0, 1 - _ease_in(u))))
OUTROS["spin"] = ("Spiral away", lambda u: _rest(yaw=-720 * _ease_in(u), roll=90 * _ease_in(u),
                                                 scale=max(0.0, 1 - _ease_in(u))))


# what each quality setting writes: codec, pixel format out, frames in, extra options, file type,
# whether frames are rendered deep (16-bit), supersampled, with a clear background
QUALITIES = {
    "standard": dict(label="Standard: H.264, plays everywhere (eBay, Instagram)", codec="libx264",
                     pix="yuv420p", inp="rgb24", opts=["-crf", "16", "-preset", "medium", "-tag:v", "avc1"],
                     ext=".mp4", deep=False, ss=1, alpha=False),
    "high": dict(label="High: H.264, near lossless, supersampled", codec="libx264", pix="yuv420p", inp="rgb24",
                 opts=["-crf", "10", "-preset", "slow", "-tag:v", "avc1"], ext=".mp4", deep=False, ss=2,
                 alpha=False),
    "hevc10": dict(label="HEVC 10-bit: smooth gradients, smaller files (plays on Apple devices)",
                   codec="libx265", pix="yuv420p10le", inp="rgb48le",
                   opts=["-crf", "12", "-preset", "medium", "-tag:v", "hvc1", "-x265-params", "log-level=error"],
                   ext=".mp4", deep=True, ss=2, alpha=False),
    "prores": dict(label="ProRes 422 HQ, 10-bit (.mov, for editing)", codec="prores_ks", pix="yuv422p10le",
                   inp="rgb48le", opts=["-profile:v", "3", "-vendor", "apl0"], ext=".mov", deep=True, ss=2,
                   alpha=False),
    "prores4444": dict(label="ProRes 4444 with a transparent background (.mov)", codec="prores_ks",
                       pix="yuva444p10le", inp="rgba64le", opts=["-profile:v", "4", "-vendor", "apl0"],
                       ext=".mov", deep=True, ss=2, alpha=True),
}
# colour tagged and converted as Rec. 709 (the sRGB primaries the card photos are in), so players
# show it as rendered instead of guessing; untagged H.264 is what makes exports look washed out
COLOUR = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def shrink_for_ebay(path: str, limit_mb: int = 140) -> str:
    """A copy small enough for eBay (150 MB at most), next to the original: H.264 at a bitrate that
    fits the length, same size and frame rate."""
    import subprocess
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run([exe, "-i", path], capture_output=True, text=True, timeout=60).stderr
    import re as _re
    m = _re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
    secs = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 10.0
    kbps = int(limit_mb * 8 * 1024 / max(secs, 1.0) * 0.92)
    out = os.path.splitext(path)[0] + "_ebay.mp4"
    r = subprocess.run([exe, "-y", "-loglevel", "error", "-i", path, "-c:v", "libx264", "-preset", "medium",
                        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
                        "-pix_fmt", "yuv420p", "-tag:v", "avc1", *COLOUR, "-movflags", "+faststart", "-an", out],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-200:])
    return out


def available_encoders() -> set:
    try:
        import subprocess
        import imageio_ffmpeg
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-encoders"], capture_output=True,
                             text=True, timeout=20).stdout
        return {c for c in ("libx264", "libx265", "prores_ks") if f" {c} " in out}
    except Exception:  # noqa: BLE001
        return set()


class Mp4Writer:
    """Video through the bundled ffmpeg in the chosen quality (H.264 by default, which plays
    everywhere), else OpenCV's own writer."""

    def __init__(self, path, w, h, fps=30, quality="standard"):
        self.path, self.w, self.h = path, w, h
        self.gen = self.cv = None
        q = QUALITIES.get(quality, QUALITIES["standard"])
        self.q = q
        try:
            import imageio_ffmpeg
            vf = "scale=out_color_matrix=bt709:out_range=tv"
            self.gen = imageio_ffmpeg.write_frames(
                path, (w, h), fps=fps, codec=q["codec"], pix_fmt_in=q["inp"], pix_fmt_out=q["pix"],
                quality=None, macro_block_size=2, ffmpeg_log_level="error",
                output_params=q["opts"] + ["-vf", vf] + COLOUR + ["-movflags", "+faststart"])
            self.gen.send(None)
        except Exception:  # noqa: BLE001
            self.gen = None
            self.q = QUALITIES["standard"]
            import cv2
            for cc in ("avc1", "mp4v"):
                vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*cc), fps, (w, h))
                if vw.isOpened():
                    self.cv = vw
                    break
            if self.cv is None:
                raise RuntimeError("No video encoder is available on this Mac.")

    def add(self, img: QImage):
        deep = self.gen is not None and self.q["inp"] in ("rgb48le", "rgba64le")
        if deep:
            q = img.convertToFormat(QImage.Format_RGBA64)
            if q.width() != self.w or q.height() != self.h:
                q = q.scaled(self.w, self.h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            a = np.frombuffer(q.constBits(), np.uint16).reshape(q.height(), q.bytesPerLine() // 2)[:, :self.w * 4]
            a = a.reshape(self.h, self.w, 4)
            if self.q["inp"] == "rgb48le":
                a = a[..., :3]
            self.gen.send(np.ascontiguousarray(a).astype("<u2").tobytes())
            return
        q = img.convertToFormat(QImage.Format_RGB888)
        if q.width() != self.w or q.height() != self.h:
            q = q.scaled(self.w, self.h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        a = np.frombuffer(q.constBits(), np.uint8).reshape(q.height(), q.bytesPerLine())[:, :self.w * 3]
        a = np.ascontiguousarray(a)
        if self.gen is not None:
            self.gen.send(a.tobytes())
        else:
            import cv2
            self.cv.write(cv2.cvtColor(a.reshape(self.h, self.w, 3), cv2.COLOR_RGB2BGR))

    def close(self):
        if self.gen is not None:
            self.gen.close()
        if self.cv is not None:
            self.cv.release()


class CardView(QOpenGLWidget):
    """Drag to turn the card any way you like; let go and it glides to a stop.
    At rest it leans a little toward the pointer, so the foil tracks your hand."""

    MODES = {"off": -1, "whole": 0, "art": 1, "reverse": 2}
    PATTERNS = ["linear", "radial", "sunburst", "ice", "glitter"]
    LAYER_DEFAULT = {"on": False, "depth": 0.6, "frame": 0.045, "fg_light": 1.12, "bg_light": 0.88,
                     "frame_foil": 1.0, "bg_foil": 1.0, "fg_foil": 0.0, "dof_on": 0.0, "dof": 0.5}
    LIGHTS = ["classic", "studio", "softbox", "dramatic", "sunset"]
    LIGHT_DEFAULT = {"mode": "studio", "gloss": 0.6, "exposure": 1.0, "shadow": 0.45, "dof_on": 0.0, "dof": 0.5,
                     "env_on": 1.0, "env": 0.6, "focus": 0.0, "bloom": 0.3, "vignette": 0.25, "grain": 0.12,
                     "floor_on": 0.0, "floor": 0.35, "drift": 0.35}
    FX_DEFAULT = {"pattern": "linear", "dispersion": 1.0, "scale": 38.0, "saturation": 0.6, "response": 1.0,
                  "sparkle": 0.6}

    def __init__(self, front, back, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat.defaultFormat()
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)          # stacked cards sit fractions of a millimetre apart
        self.setFormat(fmt)
        self.front_np = front
        self.layers = None                   # dict(matte, bg) when the face is split into layers
        self.lay = dict(self.LAYER_DEFAULT)
        self.front_img = _to_qimage(front)
        self.back_img = _to_qimage(back) if back is not None else None
        self.radius = card_radius(front, back)
        self._has_card = front is not None
        self.on_space = None
        self.yaw, self.pitch = REST
        self.dist = 1.0                     # zoom: 1 frames the whole card with room for the controls
        self.hover = QPointF(0, 0)          # -1..1 across the widget
        self.lean = QPointF(0, 0)
        self.holo = 0.8
        self.fx = dict(self.FX_DEFAULT)      # the foil's pattern and how it behaves
        self.light = dict(self.LIGHT_DEFAULT)
        self.extra = _rest()                 # where an entrance has the card: offsets, roll, scale
        self._entry = None
        self.mode = "whole"
        self.spin_speed = 0.0               # degrees a second for the turntable
        self.spin_target = 0.0
        self._queue = []                    # tweens waiting their turn
        self._anim = None
        self._drag = None
        self._samples = []                  # recent pointer moves, for the fling speed
        self._t0 = self._last = time.time()
        self.bg = (0.094, 0.094, 0.102)
        self.bg_photo = None                 # BGR backdrop photo, already blurred and dimmed
        self.bg_shader = ""                  # an animated backdrop from FX_BG, or none
        self.reveal_fx = None                # a video entrance: {"kind", "secs"}, drawn over the frame
        self.env_img = None                  # the room the card reflects, None for the studio
        self._env_dirty = True
        self.cam = dict(zoom=1.0, px=0.0, py=0.0, focus=0.0)   # live camera moves
        self._cam_anim = None
        self.holder = ""                     # "", sleeve, toploader, slab, or sleeve_tl (both)
        self._rig_live = None
        self.on_holder = None                # told when a sleeving move leaves the card in a holder
        self.group = None                    # several cards at once (set_group)
        self.group_preset = "stack"
        self.group_cam = dict(yaw=0.0, pitch=0.0, zoom=1.0)   # your camera on a group, over the preset's own
        self.seq = None                      # an animation from the timeline or the nodes (anim.Sequence)
        self.seq_t = 0.0                     # where its playhead is, in seconds
        self.seq_playing = False
        self._seq_t0 = time.time()
        self.on_seq_time = None              # told the playhead's time as it plays
        self._group_t0 = time.time()
        self._group_zf = 5.0
        self.slab_text = dict(top="", name="", number="", condition="")
        self._label_dirty = True
        self._bgp_dirty = False
        self.rec = None                     # live recording: writer, size, start, frames written
        self.on_change = None               # called with (yaw, pitch) as the card moves
        self.snap = True                    # let go and the card settles face-on, front or back
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ---------- GL
    def initializeGL(self):
        f = self.context().functions()
        f.glEnable(0x0B71)                  # GL_DEPTH_TEST
        self.prog = QOpenGLShaderProgram(self)
        self.prog.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
        self.prog.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG)
        for i, name in enumerate(("aPos", "aNor", "aUv", "aFace")):
            self.prog.bindAttributeLocation(name, i)
        if not self.prog.link():
            raise RuntimeError("3D shaders failed: " + self.prog.log())
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        self._fill_vbo()
        self._make_textures()
        self.tex_matte = self.tex_bg = None
        self._make_layer_textures()
        self._fbo = None
        self.context().aboutToBeDestroyed.connect(self._cleanup)

    def _make_textures(self):
        self.tex_front = self._texture(self.front_img)
        if self.back_img is not None:
            self.tex_back = self._texture(self.back_img)
        else:
            blank = QImage(8, 8, QImage.Format_RGBA8888)
            blank.fill(Qt.gray)
            self.tex_back = self._texture(blank)

    def _cleanup(self):
        self.makeCurrent()
        for t in (getattr(self, "tex_front", None), getattr(self, "tex_back", None),
                  getattr(self, "tex_matte", None), getattr(self, "tex_bg", None), getattr(self, "tex_art", None),
                  getattr(self, "tex_frames", None)):
            if t is not None:
                t.destroy()
        for t in getattr(self, "tex_stack", None) or []:
            t.destroy()
        self.tex_stack = []
        self.tex_front = self.tex_back = self.tex_matte = self.tex_bg = self.tex_art = self.tex_frames = None
        self._fbo = self._dof_ms = self._dof_tex = self._dof_key = None
        if getattr(self, "tex_bgp", None) is not None:
            self.tex_bgp.destroy()
        self.tex_bgp = self.bgp_prog = self.quad_vbo = None
        if getattr(self, "tex_env", None) is not None:
            self.tex_env.destroy()
        self.tex_env = None
        self._env_dirty = True
        if getattr(self, "tex_label", None) is not None:
            self.tex_label.destroy()
        self.tex_label = self.case_prog = None
        self.depth_prog = self._depth_fbo = self._depth_key = None
        for g in self.group or []:
            g["tf"] = g["tb"] = g["tl"] = None
        self.case_vbos = {}
        self._label_dirty = True
        self._bgp_dirty = self.bg_photo is not None
        self.post = self.post_vbo = None
        self.doneCurrent()

    def _texture(self, q):
        t = QOpenGLTexture(q.mirrored())     # GL counts rows from the bottom
        t.setMinMagFilters(QOpenGLTexture.LinearMipMapLinear, QOpenGLTexture.Linear)
        t.setWrapMode(QOpenGLTexture.ClampToEdge)
        t.generateMipMaps()
        try:
            t.setMaximumAnisotropy(8.0)
        except Exception:  # noqa: BLE001
            pass
        return t

    def has_card(self):
        return self._has_card

    def showEvent(self, e):
        super().showEvent(e)
        self._last = time.time()
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self.rec is None:
            self.timer.stop()          # nothing to draw while another tab is showing

    def event(self, e):
        # keys the viewer uses win over the window's own shortcuts while it has focus
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ShortcutOverride and e.modifiers() in (Qt.NoModifier, Qt.KeypadModifier) and \
                e.key() in (Qt.Key_Space, Qt.Key_F, Qt.Key_S, Qt.Key_R, Qt.Key_Left, Qt.Key_Right):
            e.accept()
            return True
        return super().event(e)

    def set_layers(self, data):
        """data from layers.build (matte 0..1, bg BGR), or None to go back to one flat face.
        Layers from your own PNGs bring their own composite face, shown as the front."""
        self.layers = data
        if data and data.get("manual"):
            if getattr(self, "_auto_front", None) is None:
                self._auto_front = (self.front_np, self.front_img)
            self.front_img = _to_qimage(data["img"])
            if getattr(self, "tex_front", None) is not None:
                self.makeCurrent()
                self.tex_front.destroy()
                self.tex_front = self._texture(self.front_img)
                self.doneCurrent()
        elif getattr(self, "_auto_front", None) is not None:
            self.front_np, self.front_img = self._auto_front
            self._auto_front = None
            if getattr(self, "tex_front", None) is not None:
                self.makeCurrent()
                self.tex_front.destroy()
                self.tex_front = self._texture(self.front_img)
                self.doneCurrent()
        if getattr(self, "tex_front", None) is not None:
            self.makeCurrent()
            self._make_layer_textures()
            self.doneCurrent()
        self.update()

    def _make_layer_textures(self):
        for t in (getattr(self, "tex_matte", None), getattr(self, "tex_bg", None), getattr(self, "tex_art", None),
                  getattr(self, "tex_frames", None)):
            if t is not None:
                t.destroy()
        self.tex_matte = self.tex_bg = self.tex_art = self.tex_frames = None
        for t in getattr(self, "tex_stack", None) or []:
            t.destroy()
        self.tex_stack, self.stack_info = [], []
        for item in ((self.layers or {}).get("stack") or [])[:STACK_N]:
            self.tex_stack.append(self._stack_texture(item["bgra"]))
            self.stack_info.append((float(item["depth"]), 1.0 if item["kind"] == "subject" else 0.0))
        if self.layers and self.layers.get("art") is not None:
            self.tex_art = self._texture(_to_qimage(self.layers["art"]))
        if self.layers and self.layers.get("frames") is not None:
            self.tex_frames = self._texture(_to_qimage(self.layers["frames"]))
        if self.layers:
            m = (np.clip(self.layers["matte"], 0, 1) * 255).astype(np.uint8)
            sf = (np.clip(self.layers.get("surface", np.zeros_like(self.layers["matte"])), 0, 1) * 255).astype(np.uint8)
            lo = (np.clip(self.layers.get("surface_below", np.zeros_like(self.layers["matte"])), 0, 1) * 255
                  ).astype(np.uint8)
            # BGR: R the subject, G frames above it (and printed text), B frames below it
            self.tex_matte = self._texture(_to_qimage(np.dstack([lo, sf, m])))
            self.tex_bg = self._texture(_to_qimage(self.layers["bg"]))

    def _stack_texture(self, bgra):
        """One parallax layer, premultiplied so its soft edges blend without a dark fringe, clamped
        so a slid layer never wraps round to its other side."""
        a = bgra[..., 3:4].astype(np.float32) / 255.0
        rgb = (bgra[..., 2::-1].astype(np.float32) * a).astype(np.uint8)       # BGR to RGB, times alpha
        rgba = np.ascontiguousarray(np.dstack([rgb, bgra[..., 3]]))
        h, w = rgba.shape[:2]
        # labelled straight RGBA so Qt uploads the premultiplied numbers as they are
        q = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        if q.height() > 2048:
            q = q.scaledToHeight(2048, Qt.SmoothTransformation)
        t = QOpenGLTexture(q.mirrored())
        t.setMinMagFilters(QOpenGLTexture.LinearMipMapLinear, QOpenGLTexture.Linear)
        t.setWrapMode(QOpenGLTexture.ClampToEdge)
        return t

    def _fill_vbo(self):
        """The card's mesh, with this card's own corner radius, then one quad for the drop shadow (uv -1..1)."""
        data = build_mesh(getattr(self, "radius", RADIUS))
        self.count = len(data) // 9
        sq = []
        for (x, y) in ((-1, -1), (1, -1), (1, 1), (-1, -1), (1, 1), (-1, 1)):
            sq += [x, y, 0, 0, 0, 1, x, y, 3]
        data = np.concatenate([data, np.array(sq, np.float32)])
        self.vbo.bind()
        self.vbo.allocate(data.tobytes(), data.nbytes)
        self.vbo.release()
        self._vbo_radius = getattr(self, "radius", RADIUS)

    def set_images(self, front, back):
        self.radius = card_radius(front, back)
        self.front_np = front
        self.layers = None
        self._auto_front = None
        self._has_card = front is not None
        self.front_img = _to_qimage(front)
        self.back_img = _to_qimage(back) if back is not None else None
        if getattr(self, "tex_front", None) is not None:
            self.makeCurrent()
            self.tex_front.destroy()
            self.tex_back.destroy()
            self._make_textures()
            self._make_layer_textures()
            if abs(getattr(self, "_vbo_radius", RADIUS) - self.radius) > 1e-6:
                self._fill_vbo()
            self.doneCurrent()
        self.update()

    def export_obj(self, path, units="m"):
        """The card as a Wavefront OBJ for Blender, Cinema 4D and the rest: rounded outline, real
        thickness, the front and back as textures and the edge as white stock. Writes the .obj, a
        .mtl beside it and two PNG textures. Real size: 63 x 88 x 0.32 mm (in metres by default)."""
        base = os.path.splitext(path)[0]
        stem = os.path.basename(base)
        k = {"m": 0.088, "cm": 8.8, "mm": 88.0}[units] / CARD_H     # scene units to real size
        tri = build_mesh(getattr(self, "radius", RADIUS)).reshape(-1, 3, 9)
        tri = tri[np.argsort(tri[:, 0, 8], kind="stable")]              # front, back, then edge
        data = tri.reshape(-1, 9)
        tex = {0: f"{stem}_front.png", 1: f"{stem}_back.png"}
        self.front_img.save(base + "_front.png")
        (self.back_img if self.back_img is not None else self.front_img).save(base + "_back.png")
        with open(base + ".mtl", "w", encoding="utf-8") as m:
            m.write("# CardCrop card\n")
            for name, t in (("card_front", tex[0]), ("card_back", tex[1])):
                m.write(f"newmtl {name}\nKa 1 1 1\nKd 1 1 1\nKs 0.25 0.25 0.25\nNs 180\nd 1\nillum 2\nmap_Kd {t}\n\n")
            m.write("newmtl card_edge\nKa 1 1 1\nKd 0.86 0.85 0.82\nKs 0.05 0.05 0.05\nNs 20\nd 1\nillum 2\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# CardCrop card, {units}\nmtllib {stem}.mtl\no card\n")
            for x, y, z in data[:, 0:3]:
                f.write(f"v {x * k:.6f} {y * k:.6f} {z * k:.6f}\n")
            for u, v in data[:, 6:8]:
                f.write(f"vt {u:.6f} {v:.6f}\n")   # v up, as OBJ expects
            for nx, ny, nz in data[:, 3:6]:
                f.write(f"vn {nx:.5f} {ny:.5f} {nz:.5f}\n")
            names = {0: "card_front", 1: "card_back", 2: "card_edge"}
            current = None
            for t in range(len(data) // 3):
                face = int(round(data[t * 3, 8]))
                if face != current:
                    f.write(f"g {names[face]}\nusemtl {names[face]}\n")
                    current = face
                a, b, c = t * 3 + 1, t * 3 + 2, t * 3 + 3
                if face == 2:
                    f.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
                else:
                    f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
        return [path, base + ".mtl", base + "_front.png", base + "_back.png"]

    def set_background(self, hex_color):
        c = hex_color.lstrip("#")
        self.bg = tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
        self.update()

    def _draw(self, w, h, yaw, pitch, dist, t, bg, extra=None, clear_alpha=True, target=None, deep=False):
        """The frame into whatever is bound, or, with camera depth of field on, into an offscreen
        buffer first and then through the lens blur onto target (the framebuffer id to end on)."""
        lt = self.light
        cam = self._cam_of(extra)
        amt = float(lt.get("dof", 0.5)) if lt.get("dof_on") else 0.0
        amt = max(amt, float(cam.get("dof_min", 0.0)))         # a focus pull brings its own lens
        seq_focus = 0.0
        if self.seq is not None and self.group:
            st = float(extra["seq_t"]) if (extra is not None and "seq_t" in extra) else self.seq_t
            _p, _l, sc = self.seq.evaluate(st)
            amt, seq_focus = max(amt, sc["dof_min"]), sc["focus"]
        bloom, vig, grain = (float(lt.get(k, 0.0)) for k in ("bloom", "vignette", "grain"))
        if max(amt, bloom, vig, grain) <= 0.0 or target is None or not self._post_ready():
            self._scene(w, h, yaw, pitch, dist, t, bg, extra, clear_alpha)
            return
        from PySide6.QtGui import QVector2D
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        f = self.context().functions()
        key = (w, h, deep)
        if getattr(self, "_dof_key", None) != key:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fmt.setSamples(4)
            plain = QOpenGLFramebufferObjectFormat()
            if deep:
                fmt.setInternalTextureFormat(0x881A)
                plain.setInternalTextureFormat(0x881A)
            self._dof_ms = QOpenGLFramebufferObject(w, h, fmt)
            self._dof_tex = QOpenGLFramebufferObject(w, h, plain)
            self._dof_key = key
        self._dof_ms.bind()
        mv, proj = self._scene(w, h, yaw, pitch, dist, t, bg, extra, clear_alpha)
        use_depth = bool(self.group) and amt > 0.0 and self._depth_pass(f, w, h, proj)
        if self.group and not use_depth:
            amt = 0.0
        QOpenGLFramebufferObject.blitFramebuffer(self._dof_tex, self._dof_ms)
        # smaller and smaller copies of the frame, for the glow
        f.glBindTexture(0x0DE1, self._dof_tex.texture())
        f.glTexParameteri(0x0DE1, 0x2801, 0x2703)           # MIN_FILTER = LINEAR_MIPMAP_LINEAR
        f.glTexParameteri(0x0DE1, 0x2802, 0x812F)           # WRAP_S = CLAMP_TO_EDGE
        f.glTexParameteri(0x0DE1, 0x2803, 0x812F)
        f.glGenerateMipmap(0x0DE1)
        f.glBindFramebuffer(0x8D40, int(target))            # GL_FRAMEBUFFER
        f.glViewport(0, 0, w, h)
        f.glDisable(0x0B71)
        f.glDisable(0x0BE2)
        q = self.post
        q.bind()
        f.glActiveTexture(0x84C0)                           # GL_TEXTURE0
        f.glBindTexture(0x0DE1, self._dof_tex.texture())
        q.setUniformValue1i("uImg", 0)
        q.setUniformValue("uPx", QVector2D(1.0 / w, 1.0 / h))
        tan_y = math.tan(math.radians(15.0))
        q.setUniformValue("uTan", QVector2D(tan_y * w / max(1, h), tan_y))
        if mv is not None:
            q.setUniformValue("uC", mv.map(QVector3D(0, 0, 0)))
            q.setUniformValue("uN", mv.mapVector(QVector3D(0, 0, 1)).normalized())
            # a tour looks at a corner or an edge: focus follows it there
            px, py = float(cam.get("px", 0.0)), float(cam.get("py", 0.0))
            q.setUniformValue1f("uZf", -mv.map(QVector3D(px * CARD_W / 2, py * CARD_H / 2, 0)).z()
                                if (px or py) else 0.0)
        q.setUniformValue1f("uUseDepth", 1.0 if use_depth else 0.0)
        if use_depth:
            f.glActiveTexture(0x84C1)
            f.glBindTexture(0x0DE1, self._depth_fbo.texture())
            f.glTexParameteri(0x0DE1, 0x2801, 0x2600)       # MIN_FILTER = NEAREST: one level, read as is
            f.glTexParameteri(0x0DE1, 0x2800, 0x2600)       # MAG_FILTER = NEAREST
            f.glActiveTexture(0x84C0)
            q.setUniformValue1i("uDepth", 1)
            q.setUniformValue1f("uZf", float(self._group_zf))
        else:
            q.setUniformValue1i("uDepth", 0)
        q.setUniformValue1f("uAmt", amt)
        q.setUniformValue1f("uFocus", float(lt.get("focus", 0.0)) + float(cam.get("focus", 0.0)) + seq_focus)
        q.setUniformValue1f("uBloom", bloom)
        q.setUniformValue1f("uVig", vig)
        q.setUniformValue1f("uGrain", grain)
        q.setUniformValue1f("uSeed", float(int(t * 60) % 997))
        self.post_vbo.bind()
        q.enableAttributeArray(0)
        q.setAttributeBuffer(0, 0x1406, 0, 2, 8)
        f.glDrawArrays(0x0004, 0, 6)
        q.disableAttributeArray(0)
        self.post_vbo.release()
        q.release()
        f.glEnable(0x0B71)

    def _rig_of(self, extra):
        """Holders placed by a move (a rig), or the sleeve-and-top-loader holder at rest."""
        if extra is not None and extra.get("rig"):
            return extra["rig"]
        if extra is None and getattr(self, "_rig_live", None):
            return self._rig_live
        if self.holder == "sleeve_tl":
            hs, _lo, _hi = _rig(SLEEVE_ON, LOADER_ON)
            return dict(holders=hs, frame=self.rest_frame("sleeve_tl"))
        if self.holder == "sleeve":
            return dict(holders=[("sleeve", SLEEVE_ON)], frame=self.rest_frame("sleeve"))
        if self.holder == "slab":                     # slabbed cards are sleeved
            # drawn at rest exactly as the slab move ends, two closed halves, so nothing changes the moment
            # the move finishes (the one-piece slab shades its window a little differently)
            return dict(holders=[h for h in mv_slab(1.0)["rig"]["holders"]], frame=self.rest_frame("slab"))
        return None

    def _cam_of(self, extra):
        """The camera for a frame: an export carries its own in extra; the live view uses its own."""
        if extra is not None:
            return {k: extra[k] for k in ("zoom", "px", "py", "focus", "dof_min", "drift_phase") if k in extra}
        return self.cam

    def set_env(self, img):
        """What the card reflects: an image of the room (BGR), or None for the studio."""
        self.env_img = img
        self._env_dirty = True
        self.update()

    def play_camera(self, name, dur=None):
        """A camera move live: push in, pull back, a corner tour."""
        if name not in CAMERA_MOVES:
            return
        label, fn, secs, own = CAMERA_MOVES[name]
        self._anim, self._queue = None, []
        self.spin_speed = self.spin_target = 0.0
        self._land_holder()
        if name in SLEEVE_ENDS:
            start = {"sleeve_in": "", "sleeve_load": "", "slab_in": "", "unsleeve": "sleeve",
                     "unload": "sleeve_tl", "unslab": "slab"}[name]
            self._start_holder_move(fn, dur or secs, start, SLEEVE_ENDS[name])
            return
        self._cam_anim = dict(fn=fn, own=own, t0=time.time(), dur=dur or secs,
                              yaw=_nearest(self.yaw, 0.0), pitch=self.pitch, end_holder=None)

    # from the holder it is in, to the one picked: (move, start, end) along that move
    # from the holder it is in to the one picked: the steps, each (move, start, end) along that move.
    # A slabbed card is sleeved: a bare card is sleeved on the way in, a loaded one loses only its
    # loader, and leaving the slab keeps the sleeve until the card is meant to be bare.
    LOAD_ONLY, UNLOAD_ONLY = ("sleeve_load", 0.42, 1.0), ("unload", 0.0, 0.58)
    HOLDER_MOVES = {("", "sleeve"): [("sleeve_in", 0.0, 1.0)],
                    ("", "sleeve_tl"): [("sleeve_load", 0.0, 1.0)],
                    ("sleeve", ""): [("unsleeve", 0.0, 1.0)],
                    ("sleeve_tl", ""): [("unload", 0.0, 1.0)],
                    ("sleeve", "sleeve_tl"): [LOAD_ONLY],
                    ("sleeve_tl", "sleeve"): [UNLOAD_ONLY],
                    ("", "slab"): [("sleeve_in", 0.0, 1.0), ("slab_in", 0.0, 1.0)],
                    ("sleeve", "slab"): [("slab_in", 0.0, 1.0)],
                    ("sleeve_tl", "slab"): [UNLOAD_ONLY, ("slab_in", 0.0, 1.0)],
                    ("slab", "sleeve"): [("unslab", 0.0, 1.0)],
                    ("slab", ""): [("unslab", 0.0, 1.0), ("unsleeve", 0.0, 1.0)],
                    ("slab", "sleeve_tl"): [("unslab", 0.0, 1.0), LOAD_ONLY]}

    # what the camera frames with each holder at rest, as a rig's frame: middle above the card (mm),
    # height and width (mm). Sleeve and top loader keep the card's own shot (the loader only centred
    # on itself, a few mm up), so putting one on never moves the camera; a slab is taller than the shot
    # and needs room, so the camera eases back to it over the move rather than jumping
    REST_FRAMES = {"": (0.0, 0.0, 0.0), "sleeve": (0.0, 0.0, 0.0), "sleeve_tl": (LOADER_ON, 0.0, 0.0),
                   "slab": (SLAB_ON, 139.7, 0.0)}

    @classmethod
    def rest_frame(cls, holder):
        return cls.REST_FRAMES.get(holder or "", (0.0, 0.0, 0.0))

    def _holder_steps(self, frm, to):
        return self.HOLDER_MOVES.get((frm, to))

    def play_holder(self, target):
        """Puts the card into the holder picked by playing the move, rather than jumping there: sleeving,
        top loading, the slab's halves closing round it, or the same backwards. Returns False when there
        is no way (the caller jumps instead)."""
        frm, to = self.holder or "", target or ""
        steps = self._holder_steps(frm, to)
        if not steps or self.group:
            return False
        parts = []
        for name, a, b in steps:
            _label, fn, secs, own = CAMERA_MOVES[name]
            parts.append((fn, a, b, secs * (b - a)))
        total = sum(p[3] for p in parts)

        def run(u, parts=parts, total=total):
            t = u * total
            for fn, a, b, d in parts:
                if t <= d or (fn, a, b, d) == parts[-1]:
                    return fn(a + (b - a) * min(1.0, t / max(1e-6, d)))
                t -= d
        self._start_holder_move(run, total, frm, to)
        return True

    def _start_holder_move(self, fn, dur, frm, to):
        self._anim, self._queue = None, []
        self.spin_speed = self.spin_target = 0.0
        self._cam_anim = dict(fn=fn, own=True, t0=time.time(), dur=dur, yaw=_nearest(self.yaw, 0.0),
                              pitch=self.pitch, end_holder=to, frames=(self.rest_frame(frm), self.rest_frame(to)),
                              from_yaw=self.yaw, from_pitch=self.pitch)
        c = fn(0.0)                                   # its first frame now: nothing blinks out meanwhile
        self._rig_live = dict(c["rig"], frame=self.rest_frame(frm)) if c.get("rig") else None
        self.holder = ""                              # the move places the holders itself
        self.update()

    def pull_focus(self, dur=1.6):
        """Rack focus live: start out of focus behind the card and pull onto it."""
        self._land_holder()
        self._cam_anim = dict(fn=lambda u: dict(focus=rack_focus(u), dof_min=0.6 * (1 - u)), own=False,
                              t0=time.time(), dur=dur, yaw=self.yaw, pitch=self.pitch)

    def set_backdrop_photo(self, img):
        """A prepared photo (prepare_backdrop_photo) behind the card, cover-fitted to the frame, or None
        for the plain colour."""
        self.bg_photo = img
        self._bgp_dirty = True
        self.update()

    def _quad(self):
        if getattr(self, "quad_vbo", None) is None:
            quad = np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], np.float32)
            b = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            b.create()
            b.bind()
            b.allocate(quad.tobytes(), quad.nbytes)
            b.release()
            self.quad_vbo = b
        return self.quad_vbo

    def set_bg_shader(self, name):
        self.bg_shader = name if name in FX_BG else ""
        self.update()

    def _fx_prog(self, key, frag):
        progs = self.__dict__.setdefault("_fx_progs", {})
        if key not in progs:
            q = QOpenGLShaderProgram(self)
            q.addShaderFromSourceCode(QOpenGLShader.Vertex, POST_VERT)
            q.addShaderFromSourceCode(QOpenGLShader.Fragment, frag)
            q.bindAttributeLocation("aXY", 0)
            if not q.link():
                print("effect shader failed:", key, q.log())
                q = None
            progs[key] = q
        return progs[key]

    def _fx_quad(self, q):
        f = self.context().functions()
        b = self._quad()
        b.bind()
        q.enableAttributeArray(0)
        q.setAttributeBuffer(0, 0x1406, 0, 2, 8)
        f.glDrawArrays(0x0004, 0, 6)
        q.disableAttributeArray(0)
        b.release()

    def _draw_bg_shader(self, w, h, t, bg):
        """The animated backdrop across the whole frame, under everything, tinted by the colour."""
        from PySide6.QtGui import QVector2D, QVector3D
        q = self._fx_prog("bg_" + self.bg_shader, FX_BG[self.bg_shader][1])
        if q is None:
            return
        f = self.context().functions()
        f.glDisable(0x0B71)
        f.glDepthMask(0)
        q.bind()
        q.setUniformValue("uRes", QVector2D(float(w), float(h)))
        q.setUniformValue1f("uT", float(t))
        q.setUniformValue("uTint", QVector3D(*[float(x) for x in bg]))
        self._fx_quad(q)
        q.release()
        f.glDepthMask(1)
        f.glEnable(0x0B71)

    def _draw_fx(self, w, h, t):
        """A video entrance over the finished frame, for its first seconds."""
        fx = self.reveal_fx
        if not fx or fx.get("kind") not in FX_REVEAL:
            return
        secs = float(fx.get("secs") or FX_REVEAL[fx["kind"]][1])
        if t > secs:
            return
        from PySide6.QtGui import QVector2D, QVector3D
        q = self._fx_prog("reveal", FX_REVEAL_FRAG)
        if q is None:
            return
        f = self.context().functions()
        f.glViewport(0, 0, w, h)
        f.glDisable(0x0B71)
        f.glDepthMask(0)
        f.glEnable(0x0BE2)                                   # blend
        if fx["kind"] == "holo":
            f.glBlendFunc(0x0302, 1)                         # light added on top: src alpha, one
        else:
            f.glBlendFunc(0x0302, 0x0303)                    # over: src alpha, one minus src alpha
        q.bind()
        q.setUniformValue("uRes", QVector2D(float(w), float(h)))
        q.setUniformValue1f("uT", float(t))
        q.setUniformValue1f("uP", float(t / secs))
        q.setUniformValue1i("uKind", {"ring": 0, "holo": 1, "lock": 2}[fx["kind"]])
        # the card's half size in the shader's units (short side = 2), framed the way fit_dist frames it
        aspect = CARD_W / CARD_H
        card_h = min(h / 1.24, w / 1.24 / aspect)
        hh = card_h / min(w, h)
        q.setUniformValue("uCard", QVector2D(hh * aspect, hh))
        ink = fx.get("ink", (0.84, 0.95, 0.29))
        q.setUniformValue("uInk", QVector3D(*[float(x) for x in ink]))
        self._fx_quad(q)
        q.release()
        f.glBlendFunc(0x0302, 0x0303)
        f.glDisable(0x0BE2)
        f.glDepthMask(1)
        f.glEnable(0x0B71)

    def _draw_photo(self, w, h):
        """The backdrop photo across the whole frame, cropped to fill it, under everything."""
        if self._bgp_dirty:
            if getattr(self, "tex_bgp", None) is not None:
                self.tex_bgp.destroy()
            self.tex_bgp = None
            if self.bg_photo is not None:
                q = _to_qimage(self.bg_photo)
                self.tex_bgp = self._texture(q)
                self._bgp_aspect = q.width() / max(1, q.height())
            self._bgp_dirty = False
        if getattr(self, "tex_bgp", None) is None:
            return
        if getattr(self, "bgp_prog", None) is None:
            q = QOpenGLShaderProgram(self)
            q.addShaderFromSourceCode(QOpenGLShader.Vertex, POST_VERT)
            q.addShaderFromSourceCode(QOpenGLShader.Fragment, BGP_FRAG)
            q.bindAttributeLocation("aXY", 0)
            if not q.link():
                print("backdrop photo shader failed:", q.log())
                self.tex_bgp = None
                return
            self.bgp_prog = q
        from PySide6.QtGui import QVector2D
        f = self.context().functions()
        ai, av = self._bgp_aspect, w / max(1, h)
        scale = QVector2D(1.0, ai / av) if av > ai else QVector2D(av / ai, 1.0)
        f.glDisable(0x0B71)
        f.glDepthMask(0)
        q = self.bgp_prog
        q.bind()
        self.tex_bgp.bind(0)
        q.setUniformValue1i("uImg", 0)
        q.setUniformValue("uScale", scale)
        b = self._quad()
        b.bind()
        q.enableAttributeArray(0)
        q.setAttributeBuffer(0, 0x1406, 0, 2, 8)
        f.glDrawArrays(0x0004, 0, 6)
        q.disableAttributeArray(0)
        b.release()
        q.release()
        f.glDepthMask(1)
        f.glEnable(0x0B71)

    def _post_ready(self):
        if getattr(self, "post", None) is not None:
            return True
        if getattr(self, "_post_failed", False):
            return False
        q = QOpenGLShaderProgram(self)
        q.addShaderFromSourceCode(QOpenGLShader.Vertex, POST_VERT)
        q.addShaderFromSourceCode(QOpenGLShader.Fragment, POST_FRAG)
        q.bindAttributeLocation("aXY", 0)
        if not q.link():
            print("depth of field shader failed:", q.log())
            self._post_failed = True
            return False
        self.post, self.post_vbo = q, self._quad()
        return True

    def _scene(self, w, h, yaw, pitch, dist, t, bg, extra=None, clear_alpha=True):
        if self.group:
            return self._scene_group(w, h, yaw, pitch, dist, t, bg, extra, clear_alpha)
        from PySide6.QtGui import QVector2D
        f = self.context().functions()
        f.glViewport(0, 0, w, h)
        f.glClearColor(*bg, 1.0 if clear_alpha else 0.0)
        f.glClear(0x4000 | 0x0100)
        if clear_alpha and self.bg_photo is not None:
            self._draw_photo(w, h)
        elif clear_alpha and self.bg_shader in FX_BG:
            self._draw_bg_shader(w, h, t, bg)
        proj = QMatrix4x4()
        proj.perspective(30.0, max(1, w) / max(1, h), 0.05, 50.0)
        ex = extra or self.extra
        cam = self._cam_of(extra)
        zoom = max(0.2, float(cam.get("zoom", 1.0)))
        lt0 = self.light
        on_floor = bool(lt0.get("floor_on")) and float(lt0.get("floor", 0.0)) > 0.0
        rig = self._rig_of(extra)
        hd = None if rig else HOLDERS.get(self.holder)
        hold_h = hd["h"] * MM if hd else CARD_H
        lift = 0.12 * CARD_H / zoom if on_floor else 0.0     # room under the card for its reflection
        fit = max(1.0, hold_h / CARD_H * 0.97)
        if rig:
            fr_cy, fr_h, fr_w = rig["frame"]
            fit = max(1.0, fr_h * MM / CARD_H * 0.97, fr_w * MM / CARD_W * 0.97)
        dist = dist / zoom * (1.1 if on_floor else 1.0) * fit
        # the near plane as far out as the shot allows, so depth is precise where the card is
        proj = QMatrix4x4()
        proj.perspective(30.0, max(1, w) / max(1, h), max(0.05, 0.5 * (dist - 1.6 * max(hold_h, CARD_H))), 50.0)
        mv = QMatrix4x4()
        mv.translate(0, lift, 0)
        mv.translate(ex["ox"] * CARD_H, ex["oy"] * CARD_H, -dist)
        mv.rotate(ex["roll"], 0, 0, 1)
        mv.rotate(pitch, 1, 0, 0)
        mv.rotate(yaw, 0, 1, 0)
        mv.scale(max(0.001, ex["scale"]))
        if rig:
            mv.translate(0, -fr_cy * MM, 0)                # turn round the middle of what is in shot
        hold_mv = QMatrix4x4(mv)
        if hd:
            mv.translate(0, hd["card_y"] * MM, 0)        # the holder turns round its own centre
        # a camera move: slide sideways so a point on the card (px, py from -1 to 1 across it) sits in the middle
        px, py = float(cam.get("px", 0.0)), float(cam.get("py", 0.0))
        shift = QVector3D(0, 0, 0)
        if px or py:
            o = mv.map(QVector3D(0, 0, 0))
            shift = mv.map(QVector3D(px * CARD_W / 2, py * CARD_H / 2, 0)) - o
            shift.setZ(0)
            pre = QMatrix4x4()
            pre.translate(-shift)
            mv = pre * mv
            hold_mv = pre * hold_mv
        # every holder in shot, inner first: (name, model-view)
        if rig:
            holders = []
            for nm, dy, *dz in rig["holders"]:
                hm = QMatrix4x4(hold_mv)
                hm.translate(0, dy * MM, (dz[0] if dz else 0.0) * MM)
                holders.append((nm, hm))
            bottom = min([-44.0] + [h_[1] - HOLDERS[h_[0]]["h"] / 2 for h_ in rig["holders"]])
        else:
            holders = [(self.holder, hold_mv)] if hd else []
        p = self.prog
        p.bind()
        p.setUniformValue("uMvp", proj * mv)
        p.setUniformValue("uMv", mv)
        p.setUniformValue("uNorm", mv.normalMatrix())
        p.setUniformValue1f("uHolo", 0.0 if self.mode == "off" else float(self.holo))
        p.setUniformValue1f("uMode", float(max(0, self.MODES[self.mode])))
        p.setUniformValue1f("uTime", float(t))
        fx = self.fx
        p.setUniformValue1f("uPattern", float(self.PATTERNS.index(fx["pattern"]) if fx["pattern"] in self.PATTERNS else 0))
        p.setUniformValue1f("uDisp", float(fx["dispersion"]))
        p.setUniformValue1f("uFreq", float(fx["scale"]))
        p.setUniformValue1f("uSat", float(fx["saturation"]))
        p.setUniformValue1f("uResp", float(fx["response"]))
        p.setUniformValue1f("uSparkle", float(fx["sparkle"]))
        p.setUniformValue("uTilt", QVector2D(math.sin(math.radians(yaw)), math.sin(math.radians(pitch))))
        p.setUniformValue("uLight", QVector3D(0.35, 0.55, 1.0))
        lt = self.light
        p.setUniformValue1f("uLightMode", float(self.LIGHTS.index(lt["mode"]) if lt["mode"] in self.LIGHTS else 1))
        p.setUniformValue1f("uGloss", float(lt["gloss"]))
        p.setUniformValue1f("uExposure", float(lt["exposure"]))
        p.setUniformValue("uCenter", mv.map(QVector3D(0, 0, 0)))
        p.setUniformValue("uEdge", QVector3D(0.86, 0.85, 0.82))
        self.tex_front.bind(0)
        self.tex_back.bind(1)
        p.setUniformValue1i("uFront", 0)
        p.setUniformValue1i("uBack", 1)
        lay = self.lay
        on = bool(lay.get("on") and self.layers and getattr(self, "tex_matte", None) is not None)
        p.setUniformValue1f("uLayers", 1.0 if on else 0.0)
        if on:
            self.tex_matte.bind(2)
            self.tex_bg.bind(3)
            p.setUniformValue1i("uMatte", 2)
            p.setUniformValue1i("uBgTex", 3)
            manual = bool(self.layers.get("manual"))
            (self.tex_art if getattr(self, "tex_art", None) is not None else self.tex_bg).bind(4)
            p.setUniformValue1i("uArt", 4)
            (self.tex_frames if getattr(self, "tex_frames", None) is not None else self.tex_front).bind(5)
            p.setUniformValue1i("uFrames", 5)
            p.setUniformValue1f("uManual", 1.0 if manual and getattr(self, "tex_art", None) is not None else 0.0)
            p.setUniformValue("uLayerA", QVector4D(float(lay["depth"]), 0.0 if manual else float(lay["frame"]),
                                                   float(lay["fg_light"]), float(lay["bg_light"])))
            p.setUniformValue1f("uDof", float(lay.get("dof", 0.5)) if lay.get("dof_on") else 0.0)
            stack = getattr(self, "tex_stack", None) or [] if manual else []
            p.setUniformValue1f("uNS", float(len(stack)))
            for i in range(STACK_N):
                (stack[i] if i < len(stack) else self.tex_front).bind(STACK_UNIT + i)
                p.setUniformValue1i(f"uS{i}", STACK_UNIT + i)
                d, k = self.stack_info[i] if i < len(stack) else (0.0, 0.0)
                p.setUniformValue1f(f"uSD{i}", d)
                p.setUniformValue1f(f"uSK{i}", k)
            p.setUniformValue("uLayerFoil", QVector3D(float(lay["frame_foil"]), float(lay["bg_foil"]),
                                                      float(lay["fg_foil"])))
        # the room the card reflects
        if self._env_dirty or getattr(self, "tex_env", None) is None:
            if getattr(self, "tex_env", None) is not None:
                self.tex_env.destroy()
            self.tex_env = self._texture(_to_qimage(self.env_img if self.env_img is not None else studio_env()))
            self._env_dirty = False
        self.tex_env.bind(12)
        p.setUniformValue1i("uEnv", 12)
        lt = self.light
        p.setUniformValue1f("uEnvAmt", float(lt.get("env", 0.6)) if lt.get("env_on") else 0.0)
        ph = float(cam.get("drift_phase", t * 2 * math.pi / 9.0))
        da = float(lt.get("drift", 0.0))
        drift_v = (da * 0.38 * math.sin(ph), da * 0.16 * math.sin(2 * ph + 1.0))
        from PySide6.QtGui import QVector2D as _V2
        p.setUniformValue("uDrift", _V2(*drift_v))
        p.setUniformValue("uFloor", QVector4D(0, 0, 1, 0))
        self.vbo.bind()
        stride = 9 * 4
        for i, (n, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
            p.enableAttributeArray(i)
            p.setAttributeBuffer(i, 0x1406, off, n, stride)     # GL_FLOAT
        floor_on = bool(lt.get("floor_on")) and float(lt.get("floor", 0.0)) > 0.0
        yf = -0.505 * hold_h - shift.y() + lift
        if rig:
            yf = (bottom - fr_cy) * MM * 1.01 - shift.y() + lift
        if floor_on:
            # a glossy floor just under the card: the card mirrored in it, fading with depth
            fm = QMatrix4x4()
            fm.translate(0, yf, 0)
            fm.scale(1, -1, 1)
            fm.translate(0, -yf, 0)
            rmv = fm * mv
            p.setUniformValue("uMvp", proj * rmv)
            p.setUniformValue("uMv", rmv)
            p.setUniformValue("uNorm", rmv.normalMatrix())
            p.setUniformValue("uFloor", QVector4D(1.0, yf, 0.45 * CARD_H, float(lt["floor"])))
            f.glEnable(0x0BE2)
            f.glBlendFuncSeparate(0x0302, 0x0303, 0, 1)         # colour by alpha; keep the frame's alpha
            # the reflection is see-through, so lay its depth down first and colour only the nearest
            # surface: the side that faces the floor, never the far side showing through it
            f.glColorMask(False, False, False, False)
            f.glDrawArrays(0x0004, 0, self.count)
            f.glColorMask(True, True, True, True)
            f.glDepthFunc(0x0203)                               # GL_LEQUAL
            f.glDrawArrays(0x0004, 0, self.count)
            f.glDepthFunc(0x0201)                               # GL_LESS
            f.glDisable(0x0BE2)
            if holders:
                p.release()
                for nm, hm in holders:
                    self._draw_holder(f, proj, fm * hm, drift_v,
                                      QVector4D(1.0, yf, 0.45 * CARD_H, float(lt["floor"])), name=nm)
                p.bind()
                self.vbo.bind()
                for i, (n, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
                    p.enableAttributeArray(i)
                    p.setAttributeBuffer(i, 0x1406, off, n, stride)
            f.glClear(0x0100)                                   # the card itself is drawn over its reflection
            p.setUniformValue("uFloor", QVector4D(0, 0, 1, 0))
            p.setUniformValue("uMvp", proj * mv)
            p.setUniformValue("uMv", mv)
            p.setUniformValue("uNorm", mv.normalMatrix())
        sh = float(self.light.get("shadow", 0.0)) * max(0.0, 1.0 - abs(ex["oy"]) * 0.6) * min(1.0, ex["scale"])
        if sh > 0.01 and self.light["mode"] != "classic":
            # a soft shadow on a backdrop just behind the card, down and right of the key light,
            # its size following how the card is turned
            smv = QMatrix4x4()
            S = 1.6 * max(CARD_H, hold_h) * 1.15         # room for a slab's whole shadow, blur and all
            if floor_on:
                smv.translate(ex["ox"] * CARD_H - shift.x(), yf + 0.002, -dist)
                smv.rotate(-90, 1, 0, 0)
                smv.scale(S / 2, S / 2, 1.0)
                hw = (CARD_W / 2 * abs(math.cos(math.radians(yaw))) + 0.03) * ex["scale"] / (S / 2)
                hh = (CARD_W / 2 * abs(math.sin(math.radians(yaw))) + 0.05) * ex["scale"] / (S / 2)
                sh *= max(0.0, 1.0 - max(0.0, ex["oy"]) * 3.0)      # a card lifted off the floor casts less
            else:
                smv.translate(ex["ox"] * CARD_H + 0.06 * CARD_H - shift.x(), ex["oy"] * CARD_H - 0.07 * CARD_H
                              - shift.y(), -dist - 0.55)
                smv.scale(S / 2 * 1.0, S / 2 * 1.0, 1.0)
                cw_, ch_ = (hd["w"] * MM, hd["h"] * MM) if hd else (CARD_W, CARD_H)
                hw = (cw_ / 2 * abs(math.cos(math.radians(yaw))) + 0.02) * ex["scale"] / (S / 2)
                hh = (ch_ / 2 * abs(math.cos(math.radians(pitch))) + 0.02) * ex["scale"] / (S / 2)
            p.setUniformValue("uMvp", proj * smv)
            p.setUniformValue("uMv", smv)
            p.setUniformValue("uShadow", QVector4D(hw, hh, 0.09 * 1.6 * CARD_H / S, sh))
            f.glEnable(0x0BE2)                                   # GL_BLEND
            f.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)    # colour by alpha; alpha adds up
            f.glDepthMask(0)
            f.glDrawArrays(0x0004, self.count, 6)
            f.glDepthMask(1)
            f.glDisable(0x0BE2)
            p.setUniformValue("uMvp", proj * mv)
            p.setUniformValue("uMv", mv)
        f.glDrawArrays(0x0004, 0, self.count)                   # GL_TRIANGLES
        for i in range(4):
            p.disableAttributeArray(i)
        self.vbo.release()
        p.release()
        for nm, hm in holders:
            self._draw_holder(f, proj, hm, drift_v, name=nm)
        return mv, proj

    def _draw_holder(self, f, proj, hmv, drift_v, floor=None, label_tex=None, name=None):
        """The sleeve, top loader or slab over the card: its label first, then the clear shell, blended."""
        from PySide6.QtGui import QVector2D
        name = name or self.holder
        if name not in HOLDERS:
            return
        if getattr(self, "case_prog", None) is None:
            q = QOpenGLShaderProgram(self)
            q.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
            q.addShaderFromSourceCode(QOpenGLShader.Fragment, CASE_FRAG)
            for i, nm in enumerate(("aPos", "aNor", "aUv", "aFace")):
                q.bindAttributeLocation(nm, i)
            if not q.link():
                print("holder shader failed:", q.log())
                self.holder = ""
                return
            self.case_prog, self.case_vbos = q, {}
        if name not in self.case_vbos:
            data, nl = build_holder(name)
            b = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            b.create()
            b.bind()
            b.allocate(data.tobytes(), data.nbytes)
            b.release()
            self.case_vbos[name] = (b, len(data) // 9, nl)
        if label_tex is None and (self._label_dirty or getattr(self, "tex_label", None) is None):
            if getattr(self, "tex_label", None) is not None:
                self.tex_label.destroy()
            st = self.slab_text
            self.tex_label = self._texture(slab_label(st.get("top", ""), st.get("name", ""), st.get("number", ""),
                                                      st.get("condition", ""), _label_aspect()))
            self._label_dirty = False
        hd = HOLDERS[name]
        b, count, nl = self.case_vbos[name]
        q = self.case_prog
        q.bind()
        q.setUniformValue("uMvp", proj * hmv)
        q.setUniformValue("uMv", hmv)
        q.setUniformValue("uNorm", hmv.normalMatrix())
        self.tex_env.bind(12)
        q.setUniformValue1i("uEnv", 12)
        (label_tex or getattr(self, "tex_label", None) or self.tex_front).bind(13)
        q.setUniformValue1i("uLabel", 13)
        q.setUniformValue("uTint", QVector3D(*hd["tint"]))
        lk = list(hd["look"])
        lt = self.light
        lk[1] *= 0.35 + 0.65 * (float(lt.get("env", 0.6)) if lt.get("env_on") else 0.0) / 0.6   # follows Reflection
        q.setUniformValue("uLook", QVector4D(*lk))
        if hd.get("rim"):
            lh = hd["label_h"]
            q.setUniformValue("uBox", QVector4D(hd["w"], hd["h"], hd.get("divider", 0.0), hd["rim"]))
            wh_ = hd.get("win_h", lh)
            q.setUniformValue("uWells", QVector4D(hd["h"] / 2 - hd["label_top"] - wh_ / 2, wh_, hd.get("win_w", hd["label_w"]),
                                                  hd["insert"]["side"] if hd.get("insert") else 1.2))
        else:
            q.setUniformValue("uBox", QVector4D(0, 0, 0, 0))
            q.setUniformValue("uWells", QVector4D(0, 0, 0, 0))
        q.setUniformValue("uSize", QVector2D(hd["w"], hd["h"]))
        q.setUniformValue("uThick", QVector2D(*hd.get("thick", (0.0, 0.0))))
        q.setUniformValue1f("uPass", 0.0)
        q.setUniformValue1f("uHaze", float(hd.get("haze", 0.5)))
        q.setUniformValue("uRails", QVector4D(*hd.get("rails", (0.0, 0.0, 0.0, 0.0))))
        q.setUniformValue1f("uMouldFace", float(hd.get("mould_face", -1)))
        q.setUniformValue("uDrift", QVector2D(*drift_v))
        q.setUniformValue1f("uExposure", float(self.light.get("exposure", 1.0)))
        q.setUniformValue("uFloor", floor if floor is not None else QVector4D(0, 0, 1, 0))
        b.bind()
        stride = 9 * 4
        for i, (n, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
            q.enableAttributeArray(i)
            q.setAttributeBuffer(i, 0x1406, off, n, stride)
        f.glEnable(0x0BE2)
        if floor is not None:
            f.glBlendFuncSeparate(0x0302, 0x0303, 0, 1)
        if nl:
            if floor is None:
                f.glDisable(0x0BE2)
            f.glDrawArrays(0x0004, 0, nl)
            f.glEnable(0x0BE2)
        f.glDepthMask(0)
        if floor is None and hd.get("thick", (0, 0))[0] > 0:
            f.glBlendFuncSeparate(0x0306, 0, 0, 1)             # the body: multiply what shows through it
            q.setUniformValue1f("uPass", 1.0)
            f.glDrawArrays(0x0004, nl, count - nl)
            q.setUniformValue1f("uPass", 0.0)
        if floor is None:
            f.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
        f.glDrawArrays(0x0004, nl, count - nl)
        f.glDepthMask(1)
        f.glDisable(0x0BE2)
        for i in range(4):
            q.disableAttributeArray(i)
        b.release()
        q.release()

    # ---------- several cards at once
    def set_group(self, cards, preset="stack"):
        """Show several cards together, animated by a preset; cards is a list of dicts with front, back
        (numpy BGR) and label (the slab's text). None or fewer than two goes back to one card."""
        self.makeCurrent()
        for g in self.group or []:
            for k in ("tf", "tb", "tl"):
                if g.get(k) is not None:
                    g[k].destroy()
        self.doneCurrent()
        least = 1 if getattr(self, "seq", None) is not None else 2
        self.group = [dict(c) for c in (cards or [])[:GROUP_MAX]] if cards and len(cards) >= least else None
        self.group_preset = preset if preset in GROUP_PRESETS else "stack"
        self._group_t0 = time.time()
        self.update()

    def set_group_preset(self, preset):
        if preset in GROUP_PRESETS:
            self.group_preset = preset
            self._group_t0 = time.time()
            self.update()

    def group_seconds(self):
        return grp_meta(self.group_preset, len(self.group or []))["secs"]

    def _group_textures(self):
        for g in self.group:
            if g.get("tf") is None:
                g["tf"] = self._texture(_to_qimage(g.get("front")))
                g["tb"] = self._texture(_to_qimage(g.get("back")) if g.get("back") is not None else
                                        _to_qimage(None))
            if self.holder and g.get("tl") is None:
                lb = g.get("label") or {}
                g["tl"] = self._texture(slab_label(lb.get("top", ""), lb.get("name", ""), lb.get("number", ""),
                                                   lb.get("condition", ""), _label_aspect()))

    def _group_mvs(self, w, h, yaw, pitch, dist_scale, u, ex):
        """Each card's model-view (and its holder's) at moment u, the group turned by yaw and pitch."""
        n = len(self.group)
        meta = grp_meta(self.group_preset, n)
        fn = GROUP_PRESETS[self.group_preset][1]
        hd = HOLDERS.get("toploader" if self.holder == "sleeve_tl" else self.holder)
        cw = (hd["w"] * MM if hd else CARD_W) + 0.10 * CARD_H        # a cell: the card or holder, with air
        ch = (hd["h"] * MM if hd else CARD_H) + 0.08 * CARD_H
        # stacked cards touch: one card's (or holder's) thickness apart, plus a hair so they never flicker
        global STACK_GAP
        STACK_GAP = (((hd["d"] * MM) if hd else THICK) + STACK_AIR * MM) / ch
        seq_cam = None
        if self.seq is not None:
            poses, lay, seq_cam = self.seq.evaluate(self._seq_now)
            poses = (poses + [dict(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0, scale=1.0)] * n)[:n]
            lay = (lay + [dict(x=0.0, y=0.0, z=0.0)] * n)[:n]
            xs, ys = [p["x"] for p in lay], [p["y"] for p in lay]
            # frame where the cards are laid out, not where a move has thrown them
            meta = dict(w=max(xs) - min(xs) + 1.3, h=max(ys) - min(ys) + 1.35, cx=(max(xs) + min(xs)) / 2,
                        cy=(max(ys) + min(ys)) / 2, yaw=0.0, pitch=0.0, floor=min(ys) - 0.5, focus=0.0)

            def fn(u, i, n_, poses=poses):
                return poses[i]
        tan = math.tan(math.radians(15))
        aspect = w / max(1, h)
        gc = dict(self.group_cam)
        if seq_cam is not None:
            gc = dict(yaw=gc.get("yaw", 0.0) + seq_cam["yaw"], pitch=gc.get("pitch", 0.0) + seq_cam["pitch"],
                      zoom=gc.get("zoom", 1.0) * seq_cam["zoom"])
        dist = max(meta["h"] * ch * 1.08 / (2 * tan), meta["w"] * cw * 1.08 / (2 * tan * aspect)) * dist_scale \
            / max(0.3, float(gc.get("zoom", 1.0)))
        base = QMatrix4x4()
        base.translate(ex["ox"] * CARD_H, ex["oy"] * CARD_H, -dist)
        base.rotate(meta["pitch"] + pitch + float(gc.get("pitch", 0.0)), 1, 0, 0)
        base.rotate(meta["yaw"] + yaw + float(gc.get("yaw", 0.0)), 0, 1, 0)
        base.scale(max(0.001, ex["scale"]))
        base.translate(-meta["cx"] * cw, -meta["cy"] * ch, 0)
        pss = [dict(fn(u, i, n)) for i in range(n)]
        if self.seq is not None or self.group_preset != "stack":    # the stack's own path never collides
            _no_pass_through(pss, cw, ch, (hd["w"] * MM, hd["h"] * MM) if hd else (CARD_W, CARD_H),
                             [p["z"] for p in lay] if self.seq is not None else None)
        out = []
        for i in range(n):
            ps = pss[i]
            m = QMatrix4x4(base)
            if ps.get("turn"):                      # the whole layout turned as one, about its middle
                m.rotate(ps["turn"], 0, 1, 0)
            m.translate(ps["x"] * cw, ps["y"] * ch, ps["z"] * ch)
            m.rotate(ps["roll"], 0, 0, 1)
            m.rotate(ps["pitch"], 1, 0, 0)
            m.rotate(ps["yaw"], 0, 1, 0)
            if ps.get("scale", 1.0) != 1.0:
                m.scale(max(0.001, ps["scale"]))
            hm = QMatrix4x4(m)
            rig = ps.get("rig")
            if rig is not None:                     # a sleeving block decides this card's holders
                hs = []
                for nm, dy, *dz in rig:
                    hmm = QMatrix4x4(m)
                    hmm.translate(0, dy * MM, (dz[0] if dz else 0.0) * MM)
                    hs.append((nm, hmm))
                ps = dict(ps, _holders=hs)
            else:
                if hd:
                    m.translate(0, hd["card_y"] * MM, 0)
                ps = dict(ps, _holders=[("toploader" if self.holder == "sleeve_tl" else self.holder, hm)] if hd
                          else [])
            out.append((m, hm, ps))
        # the lens: on the group's middle, or on the card nearest the camera for a ring
        if meta.get("focus_front"):
            self._group_zf = min(-mm.map(QVector3D(0, 0, 0)).z() for mm, _h, _p in out)
        else:
            self._group_zf = -base.map(QVector3D(0, 0, 0)).z()
        floor_y = base.map(QVector3D(0, meta["floor"] * ch - 0.01 * CARD_H, 0)).y()
        return out, dist, floor_y

    def _scene_group(self, w, h, yaw, pitch, dist, t, bg, extra, clear_alpha):
        from PySide6.QtGui import QVector2D
        f = self.context().functions()
        f.glViewport(0, 0, w, h)
        f.glClearColor(*bg, 1.0 if clear_alpha else 0.0)
        f.glClear(0x4000 | 0x0100)
        if clear_alpha and self.bg_photo is not None:
            self._draw_photo(w, h)
        elif clear_alpha and self.bg_shader in FX_BG:
            self._draw_bg_shader(w, h, t, bg)
        self._group_textures()
        proj = QMatrix4x4()
        proj.perspective(30.0, max(1, w) / max(1, h), 0.25, 80.0)     # a near plane far enough out that a stack's layers resolve
        ex = extra or self.extra
        cam = self._cam_of(extra)
        self._seq_now = float(extra["seq_t"]) if (extra is not None and "seq_t" in extra) else self.seq_t
        if extra is not None and "group_u" in extra:
            u = float(extra["group_u"])
        else:
            u = ((time.time() - self._group_t0) / self.group_seconds()) % 1.0
        dist_scale = dist / self.fit_dist(w, h) / max(0.2, float(cam.get("zoom", 1.0)))
        cards, gdist, floor_y = self._group_mvs(w, h, yaw, pitch, dist_scale, u, ex)
        # the near plane as far out as the nearest card allows: a stack's layers are fractions of a
        # millimetre apart, and depth is only that precise when the near plane is not right at the lens
        reach = 0.75 * max(CARD_H, max((HOLDERS[nm]["h"] * MM for _m, _h, ps_ in cards for nm, _x in ps_["_holders"]
                                         if nm in HOLDERS), default=CARD_H))
        nearest = min((-m.map(QVector3D(0, 0, 0)).z() for m, _h, _p in cards), default=gdist)
        proj = QMatrix4x4()
        proj.perspective(30.0, max(1, w) / max(1, h), max(0.05, 0.5 * (nearest - reach)), 80.0)
        self._group_last = (proj, cards)
        lt = self.light
        p = self.prog
        p.bind()
        p.setUniformValue1f("uHolo", 0.0 if self.mode == "off" else float(self.holo))
        p.setUniformValue1f("uMode", float(max(0, self.MODES[self.mode])))
        p.setUniformValue1f("uTime", float(t))
        fx = self.fx
        p.setUniformValue1f("uPattern", float(self.PATTERNS.index(fx["pattern"]) if fx["pattern"] in self.PATTERNS else 0))
        p.setUniformValue1f("uDisp", float(fx["dispersion"]))
        p.setUniformValue1f("uFreq", float(fx["scale"]))
        p.setUniformValue1f("uSat", float(fx["saturation"]))
        p.setUniformValue1f("uResp", float(fx["response"]))
        p.setUniformValue1f("uSparkle", float(fx["sparkle"]))
        p.setUniformValue("uLight", QVector3D(0.35, 0.55, 1.0))
        p.setUniformValue1f("uLightMode", float(self.LIGHTS.index(lt["mode"]) if lt["mode"] in self.LIGHTS else 1))
        p.setUniformValue1f("uGloss", float(lt["gloss"]))
        p.setUniformValue1f("uExposure", float(lt["exposure"]))
        p.setUniformValue("uEdge", QVector3D(0.86, 0.85, 0.82))
        p.setUniformValue1f("uLayers", 0.0)                 # layers are for one card at a time
        if self._env_dirty or getattr(self, "tex_env", None) is None:
            if getattr(self, "tex_env", None) is not None:
                self.tex_env.destroy()
            self.tex_env = self._texture(_to_qimage(self.env_img if self.env_img is not None else studio_env()))
            self._env_dirty = False
        self.tex_env.bind(12)
        p.setUniformValue1i("uEnv", 12)
        p.setUniformValue1f("uEnvAmt", float(lt.get("env", 0.6)) if lt.get("env_on") else 0.0)
        ph = float(cam.get("drift_phase", t * 2 * math.pi / 9.0))
        da = float(lt.get("drift", 0.0))
        drift_v = (da * 0.38 * math.sin(ph), da * 0.16 * math.sin(2 * ph + 1.0))
        p.setUniformValue("uDrift", QVector2D(*drift_v))
        p.setUniformValue("uFloor", QVector4D(0, 0, 1, 0))
        p.setUniformValue1i("uFront", 0)
        p.setUniformValue1i("uBack", 1)
        stride = 9 * 4

        def attrs():
            self.vbo.bind()
            for i, (n_, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
                p.enableAttributeArray(i)
                p.setAttributeBuffer(i, 0x1406, off, n_, stride)

        def card(g, m, floor=None):
            g["tf"].bind(0)
            g["tb"].bind(1)
            gy, gp = self._card_view_angles(m)
            p.setUniformValue("uTilt", QVector2D(math.sin(math.radians(gy)), math.sin(math.radians(gp))))
            p.setUniformValue("uMvp", proj * m)
            p.setUniformValue("uMv", m)
            p.setUniformValue("uNorm", m.normalMatrix())
            p.setUniformValue("uCenter", m.map(QVector3D(0, 0, 0)))
            p.setUniformValue("uFloor", floor if floor is not None else QVector4D(0, 0, 1, 0))
            f.glDrawArrays(0x0004, 0, self.count)
        attrs()
        floor_on = bool(lt.get("floor_on")) and float(lt.get("floor", 0.0)) > 0.0
        gname = "toploader" if self.holder == "sleeve_tl" else self.holder
        hd = HOLDERS.get(gname)
        if floor_on:
            fm = QMatrix4x4()
            fm.translate(0, floor_y, 0)
            fm.scale(1, -1, 1)
            fm.translate(0, -floor_y, 0)
            fl = QVector4D(1.0, floor_y, 0.45 * CARD_H, float(lt["floor"]))
            f.glEnable(0x0BE2)
            f.glBlendFuncSeparate(0x0302, 0x0303, 0, 1)
            # depth first, then colour only the nearest surface: no far side or card behind showing through
            f.glColorMask(False, False, False, False)
            for g, (m, hm, _ps) in zip(self.group, cards):
                card(g, fm * m, fl)
            f.glColorMask(True, True, True, True)
            f.glDepthFunc(0x0203)
            for g, (m, hm, _ps) in zip(self.group, cards):
                card(g, fm * m, fl)
            f.glDepthFunc(0x0201)
            f.glDisable(0x0BE2)
            if any(ps_["_holders"] for _m, _h, ps_ in cards):
                p.release()
                for g, (m, hm, ps_) in zip(self.group, cards):
                    for nm, hmm in ps_["_holders"]:
                        self._draw_holder(f, proj, fm * hmm, drift_v, fl, label_tex=g.get("tl"), name=nm)
                p.bind()
                attrs()
            f.glClear(0x0100)
        # soft shadows, one per card: on the floor under it, or on a backdrop behind
        sh = float(lt.get("shadow", 0.0))
        if sh > 0.01 and lt["mode"] != "classic":
            S = 1.6 * max(CARD_H, (hd["h"] * MM) if hd else CARD_H) * 1.15
            f.glEnable(0x0BE2)
            f.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
            f.glDepthMask(0)
            cwh = (hd["w"] * MM, hd["h"] * MM) if hd else (CARD_W, CARD_H)
            # one backdrop behind the whole group: a card's shadow must never land on a card further back
            back_z = min(hm.map(QVector3D(0, 0, 0)).z() for _m, hm, _p in cards) - 0.55 - 0.5 * max(cwh)

            def extent(mat, w_, h_):
                """How wide, tall and deep a card (or holder) is as it is turned right now."""
                pts = [mat.map(QVector3D(sx * w_ / 2, sy * h_ / 2, 0)) for sx in (-1, 1) for sy in (-1, 1)]
                c_ = mat.map(QVector3D(0, 0, 0))
                return (max(abs(q.x() - c_.x()) for q in pts), max(abs(q.y() - c_.y()) for q in pts),
                        max(abs(q.z() - c_.z()) for q in pts))
            for m, hm, ps in cards:
                c = hm.map(QVector3D(0, 0, 0))
                big = max([cwh] + [(HOLDERS[nm]["w"] * MM, HOLDERS[nm]["h"] * MM) for nm, _x in ps["_holders"]
                                   if nm in HOLDERS], key=lambda d: d[0] * d[1])
                ex_, ey_, ez_ = extent(hm, *big)
                smv = QMatrix4x4()
                if floor_on:
                    lift_ = max(0.0, c.y() - floor_y - cwh[1] * 0.5)
                    smv.translate(c.x(), floor_y + 0.002, c.z())
                    smv.rotate(-90, 1, 0, 0)
                    smv.scale(S / 2, S / 2, 1.0)
                    hw, hh = (ex_ + 0.03) / (S / 2), (ez_ + 0.05) / (S / 2)      # its footprint, as it turns
                    k = sh * max(0.0, 1.0 - lift_ / (0.4 * CARD_H))
                else:
                    # on the backdrop, where the card's shadow falls: scaled so it still sits under the card
                    k_ = back_z / min(-0.01, c.z())
                    smv.translate((c.x() + 0.06 * CARD_H) * k_, (c.y() - 0.07 * CARD_H) * k_, back_z)
                    smv.scale(k_, k_, 1.0)
                    smv.scale(S / 2, S / 2, 1.0)
                    hw, hh = (ex_ + 0.02) / (S / 2), (ey_ + 0.02) / (S / 2)      # its outline, as it turns
                    k = sh * 0.8
                if k <= 0.01:
                    continue
                p.setUniformValue("uMvp", proj * smv)
                p.setUniformValue("uMv", smv)
                p.setUniformValue("uShadow", QVector4D(hw, hh, 0.09 * 1.6 * CARD_H / S, k))
                f.glDrawArrays(0x0004, self.count, 6)
            f.glDepthMask(1)
            f.glDisable(0x0BE2)
        # far cards first, and each nearer card nudged a step closer in depth, so where two cards lie a hair
        # apart the one in front always wins, whatever depth precision this GPU gives
        # a layout that keeps its own layers (a hand of cards) is drawn in that order, never by which
        # middle is nearer at the moment, which flips as the hand turns
        if all("layer" in c[2] for c in cards):
            order = sorted(range(len(cards)), key=lambda j: cards[j][2]["layer"])
        else:
            order = sorted(range(len(cards)), key=lambda j: cards[j][0].map(QVector3D(0, 0, 0)).z())
        f.glEnable(0x8037)                                    # GL_POLYGON_OFFSET_FILL
        for k, j in enumerate(order):
            f.glPolygonOffset(0.0, -4.0 * k)
            card(self.group[j], cards[j][0])
        f.glPolygonOffset(0.0, 0.0)
        f.glDisable(0x8037)
        for i in range(4):
            p.disableAttributeArray(i)
        self.vbo.release()
        p.release()
        # far holders first, so the clear plastic layers over what is behind it
        hs = [(hmm.map(QVector3D(0, 0, 0)).z(), j, nm, hmm) for j, (_m, _h, ps_) in enumerate(cards)
              for nm, hmm in ps_["_holders"]]
        for _z, j, nm, hmm in sorted(hs, key=lambda x: x[0]):
            self._draw_holder(f, proj, hmm, drift_v, label_tex=self.group[j].get("tl"), name=nm)
        return None, proj

    @staticmethod
    def _card_view_angles(m):
        """How a card is turned to the camera, as yaw and pitch, for the foil's response."""
        n = m.mapVector(QVector3D(0, 0, 1)).normalized()
        return math.degrees(math.asin(max(-1.0, min(1.0, n.x())))), math.degrees(math.asin(max(-1.0, min(1.0, -n.y()))))

    def _depth_pass(self, f, w, h, proj):
        """Each pixel's distance from the camera, for the lens on a group of cards."""
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        if getattr(self, "depth_prog", None) is None:
            q = QOpenGLShaderProgram(self)
            q.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
            q.addShaderFromSourceCode(QOpenGLShader.Fragment, DEPTH_FRAG)
            for i, nm in enumerate(("aPos", "aNor", "aUv", "aFace")):
                q.bindAttributeLocation(nm, i)
            if not q.link():
                print("depth shader failed:", q.log())
                return False
            self.depth_prog = q
        if getattr(self, "_depth_key", None) != (w, h):
            # a float buffer for distances: the first kind this GPU accepts, with a depth buffer of its own
            self._depth_fbo = None
            for att in (QOpenGLFramebufferObject.CombinedDepthStencil, QOpenGLFramebufferObject.Depth):
                for fmt_id in (0x881A, 0x822E, 0x8814):      # RGBA16F, R32F, RGBA32F
                    fmt = QOpenGLFramebufferObjectFormat()
                    fmt.setAttachment(att)
                    fmt.setInternalTextureFormat(fmt_id)
                    fb = QOpenGLFramebufferObject(w, h, fmt)
                    if fb.isValid():
                        self._depth_fbo = fb
                        break
                if self._depth_fbo is not None:
                    break
            self._depth_key = (w, h)
        if self._depth_fbo is None or not self._depth_fbo.isValid():
            return False                                    # no lens on the group rather than a wrong one
        _proj, cards = self._group_last
        if not self._depth_fbo.bind():
            return False
        f.glViewport(0, 0, w, h)
        f.glClearColor(1000.0, 0, 0, 1)
        f.glClear(0x4000 | 0x0100)
        f.glEnable(0x0B71)
        q = self.depth_prog
        q.bind()
        self.vbo.bind()
        for i, (n_, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
            q.enableAttributeArray(i)
            q.setAttributeBuffer(i, 0x1406, off, n_, 36)
        for m, hm, _ps in cards:
            q.setUniformValue("uMvp", proj * m)
            q.setUniformValue("uMv", m)
            q.setUniformValue("uNorm", m.normalMatrix())
            f.glDrawArrays(0x0004, 0, self.count)
        for i in range(4):
            q.disableAttributeArray(i)
        self.vbo.release()
        # the holders too, label and plastic, so the lens treats them as the solid things they are
        gname = "toploader" if self.holder == "sleeve_tl" else self.holder
        hv = getattr(self, "case_vbos", {}).get(gname)
        if hv is not None:
            b, count, _nl = hv
            b.bind()
            for i, (n_, off) in enumerate(((3, 0), (3, 12), (2, 24), (1, 32))):
                q.enableAttributeArray(i)
                q.setAttributeBuffer(i, 0x1406, off, n_, 36)
            for m, hm, _ps in cards:
                q.setUniformValue("uMvp", proj * hm)
                q.setUniformValue("uMv", hm)
                q.setUniformValue("uNorm", hm.normalMatrix())
                f.glDrawArrays(0x0004, 0, count)
            for i in range(4):
                q.disableAttributeArray(i)
            b.release()
        q.release()
        return True

    def play_seq(self, on=True):
        if self.seq is None:
            return
        if on and self.seq_t >= self.seq.length() - 0.02:
            self.seq_t = 0.0
        self._seq_t0 = time.time() - self.seq_t
        self.seq_playing = bool(on)

    def seek_seq(self, t):
        self.seq_t = max(0.0, float(t))
        self._seq_t0 = time.time() - self.seq_t
        self.update()

    def export_sequence(self, path, w=1080, h=1080, fps=30, bg=None, progress=None, quality="standard",
                        motion_blur=False):
        """The timeline as a video, from 0 to its end."""
        secs = self.seq.length()
        n = max(2, int(round(secs * fps)))
        wr = Mp4Writer(path, w, h, fps, quality)
        qd = wr.q
        ok = True
        S = 8 if motion_blur else 1
        cycles = max(1, round(secs / 9.0))
        try:
            for i in range(n):
                acc, img = None, None
                for s_ in range(S):
                    fi = i if S == 1 else i + (s_ + 0.5) / S * 0.5 - 0.25
                    extra = dict(_rest(), seq_t=max(0.0, fi / fps), drift_phase=2 * math.pi * cycles * fi / n)
                    img = self.render(w, h, 0.0, 0.0, fi / fps, bg, extra, deep=qd["deep"], alpha=qd["alpha"],
                                      ss=qd["ss"])
                    if S > 1:
                        a = _qimage_to_float(img)
                        acc = a if acc is None else acc + a
                wr.add(img if S == 1 else _float_to_qimage(acc / S))
                if progress and progress(i + 1, n) is False:
                    ok = False
                    break
        finally:
            wr.close()
        return ok

    def export_group(self, path, w=1080, h=1080, seconds=None, fps=30, bg=None, progress=None,
                     quality="standard", motion_blur=False, loops=1):
        """The group's animation as a video: whole loops, so it repeats without a seam."""
        secs = float(seconds or self.group_seconds() * loops)
        n = max(2, int(round(secs * fps)))
        cycles = max(1, round(secs / self.group_seconds()))
        wr = Mp4Writer(path, w, h, fps, quality)
        qd = wr.q
        yaw, pitch = self.yaw, self.pitch
        ok = True
        S = 8 if motion_blur else 1
        try:
            for i in range(n):
                acc = None
                for s_ in range(S):
                    fi = i if S == 1 else i + (s_ + 0.5) / S * 0.5 - 0.25
                    extra = dict(_rest(), group_u=(cycles * fi / n) % 1.0,
                                 drift_phase=2 * math.pi * max(1, round(secs / 9.0)) * fi / n)
                    img = self.render(w, h, yaw, pitch, fi / fps, bg, extra, deep=qd["deep"], alpha=qd["alpha"],
                                      ss=qd["ss"])
                    if S == 1:
                        break
                    a = _qimage_to_float(img)
                    acc = a if acc is None else acc + a
                wr.add(img if S == 1 else _float_to_qimage(acc / S))
                if progress and progress(i + 1, n) is False:
                    ok = False
                    break
        finally:
            wr.close()
        return ok

    def set_holder(self, name, text=None):
        """Put the card in a fitted sleeve, a top loader or a graded slab; "" for none."""
        self.holder = name if (name in HOLDERS or name == "sleeve_tl") else ""
        self._rig_live = None
        if text is not None and text != self.slab_text:
            self.slab_text = dict(text)
            self._label_dirty = True
        self.update()

    def view(self):
        """What is on screen right now, the lean toward the pointer included."""
        return self.yaw + self.lean.x() * 14, self.pitch + self.lean.y() * 10

    def paintGL(self):
        r = self.devicePixelRatioF()
        y, p = self.view()
        W, H = int(self.width() * r), int(self.height() * r)
        self._draw(W, H, y, p, self.fit_dist(W, H) * 1.22 * self.dist, time.time() - self._t0, self.bg,
                   target=self.defaultFramebufferObject())


    @staticmethod
    def fit_dist(w, h):
        """Camera distance that frames the whole card, turned any way, with room around it."""
        tan = math.tan(math.radians(15))
        return max(CARD_H * 1.24 / (2 * tan), CARD_W * 1.24 / (2 * tan * (w / h)))

    def render(self, w, h, yaw, pitch, t=0.0, bg=None, extra=None, deep=False, alpha=False, ss=1):
        """One frame at an exact size, off screen, antialiased; for video and stills. deep renders
        in 16-bit float (no banding in gradients and shadows), alpha leaves the background clear,
        ss renders that many times larger and scales down for finer edges and foil."""
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
        ss = max(1, min(int(ss), 4096 // max(w, h)))        # 4K is fine as it is; never past 4096
        W, H = w * ss, h * ss
        self.makeCurrent()
        key = (W, H, deep)
        if self._fbo is None or getattr(self, "_fbo_key", None) != key:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fmt.setSamples(4)
            if deep:
                fmt.setInternalTextureFormat(0x881A)            # GL_RGBA16F
            self._fbo = QOpenGLFramebufferObject(W, H, fmt)
            self._fbo_key = key
        self._fbo.bind()
        self._draw(W, H, yaw, pitch, self.fit_dist(W, H), t, bg or self.bg, extra or _rest(), clear_alpha=not alpha,
                   target=self._fbo.handle(), deep=deep)
        if self.reveal_fx and not alpha:
            self._fbo.bind()
            self._draw_fx(W, H, t)
        img = self._fbo.toImage()
        self._fbo.release()
        self.doneCurrent()
        if deep:
            img = img.convertToFormat(QImage.Format_RGBA64)
        if ss > 1:
            img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return img

    # ---------- tweens
    def tween(self, yaw=None, pitch=None, dur=0.8, ease="inout", dist=None, then=None, queue=False):
        """Glide to a pose. yaw and pitch are absolute; queue=True waits for the running move."""
        job = dict(yaw=yaw, pitch=pitch, dist=dist, dur=max(0.01, dur), ease=EASES[ease], then=then)
        if queue and (self._anim or self._queue):
            self._queue.append(job)
        else:
            self._queue = []
            self.spin_speed = self.spin_target = 0.0
            self._start(job)

    def _start(self, job):
        self._anim = dict(job, t0=time.time(), y0=self.yaw, p0=self.pitch, d0=self.dist,
                          y1=self.yaw if job["yaw"] is None else job["yaw"],
                          p1=self.pitch if job["pitch"] is None else job["pitch"],
                          d1=self.dist if job["dist"] is None else job["dist"])

    def stop(self):
        self._anim, self._queue = None, []
        self.spin_speed = self.spin_target = 0.0

    def busy(self):
        return bool(self._anim or self._queue or self.spin_speed or self._cam_anim)

    # presets
    def spin360(self, turns=1, dur=2.4):
        self.tween(self.yaw + 360 * turns, 6.0, dur * turns ** 0.6, "inout", then=self._tidy)

    def flip(self):
        self.tween(self.yaw + 180, self.pitch, 0.9, "back", then=self._tidy)

    def show_front(self):
        self.tween(_nearest(self.yaw, 0), 0.0, 0.8, "out")

    def show_back(self):
        self.tween(_nearest(self.yaw, 180), 0.0, 0.8, "out")

    def angle(self, yaw, pitch=None):
        self.tween(_nearest(self.yaw, yaw), self.pitch if pitch is None else pitch, 0.8, "out")

    def sway(self):
        """Tilt either side so the foil sweeps across, then come back."""
        y = _nearest(self.yaw, 0)
        self.tween(y - 26, 10, 0.7, "inout")
        self.tween(y + 26, -6, 1.1, "inout", queue=True)
        self.tween(y - 12, 8, 0.9, "inout", queue=True)
        self.tween(y, 4, 0.8, "out", queue=True)

    def reset(self):
        self.tween(_nearest(self.yaw, REST[0]), REST[1], 0.7, "out", dist=1.0)

    def set_spin(self, on, speed=40.0):
        """Turntable on or off; off eases down to a stop rather than cutting."""
        self._anim, self._queue = None, []
        if on:
            self.spin_target = speed
        else:
            v = self.spin_speed
            self.spin_speed = self.spin_target = 0.0
            if abs(v) > 1:
                self._fling(v, 0.0)

    def _fling(self, vy, vp):
        """Glide on after a release: starts at the release speed (degrees a second)
        and eases out, so a spin winds down instead of stopping dead."""
        sp = math.hypot(vy, vp)
        dur = min(2.6, 0.5 + sp / 450)
        k = dur / 4                          # ease_out starts at 4x average speed
        y1, p1 = self.yaw + vy * k, self.pitch + vp * k
        if self.snap:                        # the glide itself lands on the nearest face, level
            y1, p1 = round(y1 / 180.0) * 180.0, round(p1 / 360.0) * 360.0
        self.tween(y1, p1, dur, "out", then=self._tidy)

    def play_entrance(self, name, dur=ENTRANCE_SECONDS):
        """Brings the card in with one of the entrances, landing face-on."""
        if name not in ENTRANCES:
            return
        self._anim, self._queue = None, []
        self.spin_speed = self.spin_target = 0.0
        self._entry = dict(fn=ENTRANCES[name][1], t0=time.time(), dur=dur, yaw=0.0, pitch=0.0)

    def play_outro(self, name, dur=ENTRANCE_SECONDS):
        """Sends the card out of frame; a moment later it is back at rest."""
        if name not in OUTROS:
            return
        self._anim, self._queue = None, []
        self.spin_speed = self.spin_target = 0.0
        self._entry = dict(fn=OUTROS[name][1], t0=time.time(), dur=dur, yaw=0.0, pitch=0.0, hold=0.7)

    def snap_center(self):
        """Settle face-on: the nearest of front or back, level, with a slight overshoot."""
        y1, p1 = round(self.yaw / 180.0) * 180.0, round(self.pitch / 360.0) * 360.0
        if abs(y1 - self.yaw) > 0.3 or abs(p1 - self.pitch) > 0.3:
            self.tween(y1, p1, 0.55, "back", then=self._tidy)

    def _tidy(self):
        """Keep the numbers small after full turns so presets take the short way."""
        self.yaw = (self.yaw + 180) % 360 - 180
        self.pitch = (self.pitch + 180) % 360 - 180

    # ---------- motion
    def _tick(self):
        now = time.time()
        dt = min(0.05, now - self._last)
        self._last = now
        moved = False
        en = self._entry
        if en is not None:
            u = min(1.0, (now - en["t0"]) / en["dur"])
            pose = en["fn"](u)
            self.yaw, self.pitch = en["yaw"] + pose["yaw"], en["pitch"] + pose["pitch"]
            self.extra = pose
            moved = True
            if u >= 1.0:
                if now - en["t0"] < en["dur"] + en.get("hold", 0.0):
                    self.extra = en["fn"](1.0)            # an outro waits off screen a moment
                else:
                    self._entry, self.extra = None, _rest()
                    self.yaw, self.pitch = en["yaw"], en["pitch"]
                    self._tidy()
        if self.seq is not None and self.seq_playing:
            ln = self.seq.length()
            st = now - self._seq_t0
            if st >= ln:
                if self.seq.loop:
                    self._seq_t0 = now - (st % ln)
                    st = st % ln
                else:
                    st, self.seq_playing = ln, False
            self.seq_t = st
            if self.on_seq_time:
                self.on_seq_time(st)
        ca = self._cam_anim
        if ca is not None:
            u = min(1.0, (now - ca["t0"]) / ca["dur"])
            c = ca["fn"](u)
            self.cam = dict(zoom=c.get("zoom", 1.0), px=c.get("px", 0.0), py=c.get("py", 0.0),
                            focus=c.get("focus", 0.0), dof_min=c.get("dof_min", 0.0))
            if ca["own"]:
                yw, pt = ca["yaw"] + c.get("yaw", 0.0), c.get("pitch", ca["pitch"])
                if "from_yaw" in ca:                  # turn in from where you left the card, not a jump
                    k = ease_in_out(min(1.0, u * ca["dur"] / 0.6))
                    yw = ca["from_yaw"] + (yw - ca["from_yaw"]) * k
                    pt = ca["from_pitch"] + (pt - ca["from_pitch"]) * k
                self.yaw, self.pitch = yw, pt
            rig = c.get("rig")
            if rig is not None and ca.get("frames"):
                fa, fb = ca["frames"]
                k = ease_in_out(u)
                rig = dict(rig, frame=tuple(x + (y - x) * k for x, y in zip(fa, fb)))
            self._rig_live = rig
            moved = True
            if u >= 1.0:
                self._cam_anim = None
                self.cam = dict(zoom=1.0, px=0.0, py=0.0, focus=0.0)
                self._rig_live = None
                if ca.get("end_holder") is not None:
                    self.holder = ca["end_holder"]
                    if self.on_holder:
                        self.on_holder(self.holder)
                self._tidy()
        a = self._anim
        if a is not None and self._drag is None and en is None:
            u = min(1.0, (now - a["t0"]) / a["dur"])
            e = a["ease"](u)
            self.yaw = a["y0"] + (a["y1"] - a["y0"]) * e
            self.pitch = a["p0"] + (a["p1"] - a["p0"]) * e
            self.dist = a["d0"] + (a["d1"] - a["d0"]) * e
            moved = True
            if u >= 1.0:
                self._anim = None
                if a["then"]:
                    a["then"]()
                if self._queue:
                    self._start(self._queue.pop(0))
        if self.spin_target or self.spin_speed:
            self.spin_speed += (self.spin_target - self.spin_speed) * min(1.0, dt * 2.5)   # ease in
            self.yaw += self.spin_speed * dt
            if self.yaw > 540:
                self.yaw -= 360
            moved = True
        target = self.hover if (self.underMouse() and self._drag is None and not self.busy()) else QPointF(0, 0)
        d = target - self.lean
        if abs(d.x()) > 0.002 or abs(d.y()) > 0.002:
            self.lean += d * 0.10
            moved = True
        if self.rec is not None:
            self._rec_frame(now)
        if moved and self.on_change:
            self.on_change(self.yaw, self.pitch)
        if moved or self.mode != "off" or self.group:
            self.update()

    def _land_holder(self):
        """A sleeving move cut short (the card grabbed, or another move started): the holders it was placing
        went with it and the card was left bare, so the top loader vanished. It lands in the holder the move
        was heading for instead."""
        ca = self._cam_anim
        if ca is not None and ca.get("end_holder") is not None:
            self._cam_anim, self._rig_live = None, None
            self.holder = ca["end_holder"]
            if self.on_holder:
                self.on_holder(self.holder)

    def mousePressEvent(self, e):
        self._anim, self._queue = None, []
        self._land_holder()
        self._cam_anim = None
        self._rig_live = None
        self.cam = dict(zoom=1.0, px=0.0, py=0.0, focus=0.0)
        if self._entry is not None:
            self._entry, self.extra = None, _rest()
        self.spin_speed = self.spin_target = 0.0
        self._drag = e.position()
        self._samples = [(time.time(), 0.0, 0.0)]

    def mouseMoveEvent(self, e):
        p = e.position()
        self.hover = QPointF((p.x() / max(1, self.width()) - 0.5) * 2, (p.y() / max(1, self.height()) - 0.5) * 2)
        if self._drag is not None:
            d = p - self._drag
            self._drag = p
            dy, dp = d.x() * 0.45, d.y() * 0.45
            self.yaw += dy
            self.pitch += dp
            now = time.time()
            self._samples = [s for s in self._samples if now - s[0] < 0.08] + [(now, dy, dp)]
            self.update()
            if self.on_change:
                self.on_change(self.yaw, self.pitch)

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        self._drag = None
        now = time.time()
        s = [x for x in self._samples if now - x[0] < 0.08]
        if len(s) >= 2:
            span = max(0.016, now - s[0][0])
            vy, vp = sum(x[1] for x in s) / span, sum(x[2] for x in s) / span
            if math.hypot(vy, vp) > 40:
                self._fling(vy, vp)
                return
        if self.snap:
            self.snap_center()

    def mouseDoubleClickEvent(self, e):
        self.reset()

    def wheelEvent(self, e):
        self.dist = max(0.55, min(2.0, self.dist * (0.92 if e.angleDelta().y() > 0 else 1.08)))
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Left:
            self._fling(-500, 0)
        elif k == Qt.Key_Right:
            self._fling(500, 0)
        elif k == Qt.Key_F:
            self.flip()
        elif k == Qt.Key_S:
            self.spin360()
        elif k == Qt.Key_R:
            self.reset()
        elif k == Qt.Key_Space and self.on_space:
            self.on_space()
        else:
            super().keyPressEvent(e)

    # ---------- video
    def export_turntable(self, path, w=1080, h=1080, seconds=6.0, fps=30, motion="loop", bg=None,
                         progress=None, entrance="", outro="", quality="standard", camera="", motion_blur=False,
                         focus_pull=False):
        """A full turn rendered frame by frame at an exact size, so it is smooth whatever
        the screen does. camera adds a move (push in, pull back) over the motion; a motion that is a
        camera move of its own (a corner tour) sets the card and the camera together. motion_blur
        blends several moments within each frame, like a film camera's open shutter. focus_pull
        starts out of focus and pulls onto the card. progress(i, n) may return False to cancel."""
        n = max(2, int(round(seconds * fps)))
        if motion in CAMERA_MOVES:
            mv_fn = CAMERA_MOVES[motion][1]
            base = PATHS["eased"]

            def fn(t):
                c = mv_fn(t)
                return c.get("yaw", 0.0), c.get("pitch", 6.0), c
        else:
            base = PATHS[motion]
            cm = CAMERA_MOVES.get(camera, (None, None))[1]

            def fn(t):
                y, p = base(t)
                return y, p, (cm(t) if cm else {})
        ent = ENTRANCES.get(entrance, (None, None))[1]
        # the entrance takes its own time at the start, then the motion plays in what is left
        out = OUTROS.get(outro, (None, None))[1]
        ne = min(int(round(ENTRANCE_SECONDS * fps)), n // 3 if out else n // 2) if ent else 0
        no = min(int(round(ENTRANCE_SECONDS * fps)), n // 3 if ent else n // 2) if out else 0
        m = n - ne - no
        y0, p0, c0 = fn(0.0)
        loop = motion == "loop"
        rack = int(round(1.4 * fps)) if focus_pull else 0
        cycles = max(1, round(seconds / 9.0))         # the light's drift comes back to where it began

        def pose(fi):
            """Where everything is at frame fi (fractions allowed, for motion blur)."""
            fi = max(0.0, min(n - 1.0, fi))
            if fi < ne:
                pz = ent(fi / max(1, ne - 1))
                yaw, pitch, extra = y0 + pz["yaw"], p0 + pz["pitch"], dict(pz, **c0)
            elif fi >= ne + m:
                y1, p1, c1 = fn(1.0 if not loop else (m - 1) / m)
                pz = out(min(1.0, (fi - ne - m) / max(1, no - 1)))
                yaw, pitch, extra = y1 + pz["yaw"], p1 + pz["pitch"], dict(pz, **c1)
            else:
                k = fi - ne
                yaw, pitch, c = fn(k / m if loop else min(1.0, k / max(1, m - 1)))
                extra = dict(_rest(), **c)
            extra["drift_phase"] = 2 * math.pi * cycles * fi / n
            if rack and fi < rack:
                u = fi / rack
                extra["focus"] = extra.get("focus", 0.0) + rack_focus(u)
                extra["dof_min"] = max(extra.get("dof_min", 0.0), 0.6 * (1 - u))
            return yaw, pitch, extra

        wr = Mp4Writer(path, w, h, fps, quality)
        qd = wr.q
        ok = True
        S = 8 if motion_blur else 1
        try:
            for i in range(n):
                if S == 1:
                    yaw, pitch, extra = pose(i)
                    img = self.render(w, h, yaw, pitch, i / fps, bg, extra, deep=qd["deep"], alpha=qd["alpha"],
                                      ss=qd["ss"])
                else:
                    acc = None
                    for s_ in range(S):
                        fi = i + (s_ + 0.5) / S * 0.5 - 0.25        # a 180-degree shutter round the frame
                        yaw, pitch, extra = pose(fi)
                        a = _qimage_to_float(self.render(w, h, yaw, pitch, fi / fps, bg, extra, deep=qd["deep"],
                                                         alpha=qd["alpha"], ss=qd["ss"]))
                        acc = a if acc is None else acc + a
                    img = _float_to_qimage(acc / S)
                wr.add(img)
                if progress and progress(i + 1, n) is False:
                    ok = False
                    break
        finally:
            wr.close()
        return ok

    def start_recording(self, path, w=1080, h=1080, fps=30, bg=None):
        """Capture whatever you do (drags, presets, the turntable) until stop_recording."""
        self.rec = dict(writer=Mp4Writer(path, w, h, fps), w=w, h=h, fps=fps, t0=time.time(), n=0, bg=bg,
                        path=path)

    def _rec_frame(self, now):
        r = self.rec
        due = int((now - r["t0"]) * r["fps"]) + 1
        if due <= r["n"]:
            return
        y, p = self.view()
        img = self.render(r["w"], r["h"], y, p, now - self._t0, r["bg"], dict(self.extra, **self.cam))
        while r["n"] < due:                  # a slow frame is held, so timing stays true
            r["writer"].add(img)
            r["n"] += 1

    def stop_recording(self):
        r, self.rec = self.rec, None
        if r is None:
            return None, 0
        r["writer"].close()
        return r["path"], r["n"] / r["fps"]
