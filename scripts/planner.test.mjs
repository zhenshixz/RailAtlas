import test from 'node:test';
import assert from 'node:assert/strict';
import {directDestinations,timeline} from '../src/planner.js';

const stations=[{name:'出发'},{name:'目的'},{name:'上游'}];
function route(code,arrival){return {id:code,code,kind:'G',stops:[{name:'上游',arrival:'----',departure:'09:00',dayDiff:'0'},{name:'出发',arrival:'09:58',departure:'10:00',dayDiff:'0'},{name:'目的',arrival,departure:'----',dayDiff:'0'}]};}
test('direct median uses downstream arrivals and deduplicates the same service',()=>{
  const routes=[route('G1','11:40'),route('G2','11:50'),route('G3','12:10'),{...route('G1','11:40'),id:'duplicate-version'}];
  const results=directDestinations(routes,'出发',stations);
  assert.equal(results.length,1);assert.equal(results[0].station.name,'目的');
  assert.equal(results[0].median,110);assert.equal(results[0].count,3);
  assert.equal(results[0].min,100);assert.equal(results[0].max,130);
  assert.equal(results[0].trips[0].start,1);assert.equal(results[0].trips[0].end,2);
});
test('even counts use the average of both middle durations',()=>{
  const result=directDestinations([route('G1','10:20'),route('G2','10:50'),route('G3','11:20'),route('G4','11:40')],'出发',stations)[0];
  assert.equal(result.median,65);
});
test('midnight boarding is measured from departure, not arrival at the origin',()=>{
  const overnight={id:'D1',code:'D1',kind:'D',stops:[{name:'出发',arrival:'23:58',departure:'00:05',dayDiff:'0'},{name:'目的',arrival:'01:00',departure:'----',dayDiff:'1'}]};
  const result=directDestinations([overnight],'出发',stations)[0];
  assert.equal(result.median,55);assert.equal(result.trips[0].arrivalDay,0);
});
test('day offsets and missing offsets both support overnight trips',()=>{
  const overnight={id:'D2',code:'D2',kind:'D',stops:[{name:'出发',arrival:'----',departure:'23:30',dayDiff:'0'},{name:'目的',arrival:'01:00',departure:'----',dayDiff:'1'}]};
  assert.equal(directDestinations([overnight],'出发',stations)[0].median,90);
  assert.equal(directDestinations([{...overnight,stops:overnight.stops.map(({dayDiff,...stop})=>stop)}],'出发',stations)[0].median,90);
  assert.equal(directDestinations([{...overnight,stops:[overnight.stops[0],{...overnight.stops[1],dayDiff:'2'}]}],'出发',stations)[0].median,1530);
});
test('invalid and unavailable times never create invented destinations',()=>{
  assert.equal(timeline([{arrival:'10:00',departure:'10:01',dayDiff:'0'},{arrival:'09:00',departure:'----',dayDiff:'0'}]),null);
  assert.deepEqual(directDestinations([route('G1','----')],'出发',stations),[]);
  assert.deepEqual(directDestinations([route('G1','24:01')],'出发',stations),[]);
  const terminus={...route('G1','11:00'),stops:[{name:'出发',arrival:'10:00',departure:'----'},{name:'目的',arrival:'11:00',departure:'----'}]};
  assert.deepEqual(directDestinations([terminus],'出发',stations),[]);
});
