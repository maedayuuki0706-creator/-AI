'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
const app=fs.readFileSync(path.join(__dirname,'..','app.js'),'utf8');
const ids=Array.from(html.matchAll(/\bid="([^"]+)"/g),x=>x[1]);
assert.equal(ids.length,new Set(ids).size,'duplicate HTML ids');
for(const id of ['home','home-title','home-next-race','home-next-time','home-race-count',
 'home-motor-count','home-motor-updated','deadlines','deadline-items','deadline-status',
 'race-center','tab-motor','view-motor','tab-player','view-race','view-pt2']) {
 assert.ok(ids.includes(id),'missing id '+id);
}
assert.ok(html.indexOf('id="home"')<html.indexOf('id="deadlines"'),'home before deadlines');
assert.ok(html.indexOf('live_schedule.js')<html.indexOf('motor_panel.js'));
assert.ok(html.indexOf('motor_panel.js')<html.indexOf('app.js'));
assert.ok(html.includes('meta name="description"'),'SEO description');
assert.ok(html.includes('property="og:title"'),'social title');
assert.ok(html.includes('data-open-tab="motor"'),'home motor CTA');
assert.ok(app.includes('window.MotorPanel?.start'),'race-to-motor data bridge');
assert.ok(app.includes("if(tab==='motor')"),'motor tab loading');
assert.ok(!app.includes("state={day:'',venue:'20',race:8"),'no hard-coded Wak amatsu');
console.log('PASS home nav, unique ids, script order, SEO, motor hook and no stale default');
