"""Exercise generated hub input/composition handlers with synthetic rows only."""
import json
import re
import shutil
import subprocess
import unittest
from generate_item_pages import HUB_FILTER_SCRIPT


SCRIPT = re.search(r"<script>(.*?)</script>", HUB_FILTER_SCRIPT, re.S).group(1)
HARNESS = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const script=JSON.parse(process.argv[1]);
const document={activeElement:null};let writes=0;
const rows=['仮想薬甲 製造元甲','仮想薬乙 製造元乙','参考案内 丙'].map((text,i)=>{
 let hidden=false;
 return {textContent:text,get hidden(){return hidden;},set hidden(v){writes++;hidden=v;},
  getAttribute:name=>name==='data-search'?text:name==='data-price-info'?(i<2?'1':'0'):null};
});
const node=extra=>Object.assign({hidden:true,handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}},extra);
const groups=rows.map(row=>node({hidden:false,querySelectorAll:()=>[row]}));
const nodes={hubFilter:node(),hubItems:node({querySelectorAll:selector=>selector==='li'?rows:groups}),
 hubFilterInput:node({value:'',focus(){document.activeElement=this;}}),
 hubFilterPriceOnly:node({checked:false}),hubFilterClear:node({disabled:true}),
 hubFilterCount:node({textContent:''}),hubFilterEmpty:node()};
document.getElementById=id=>nodes[id]||null;
const timers=[],url={hash:'#price-info-qa'},stored='preserved';let storageAccess=0;
const context=vm.createContext({document,window:{location:url,addEventListener(){}},
 setTimeout(fn,delay){assert.equal(delay,0);timers.push(fn);},
 localStorage:{getItem(){storageAccess++;throw Error('unexpected storage');},setItem(){storageAccess++;throw Error('unexpected storage');}}});
vm.runInContext(script,context);
const input=nodes.hubFilterInput,price=nodes.hubFilterPriceOnly;
const visible=()=>rows.map((row,i)=>row.hidden?null:i).filter(i=>i!==null);
function dispatch(type){if(input.handlers[type])input.handlers[type]({type});}
function search(value){input.value=value;dispatch('input');}
function end(value){input.value=value;dispatch('compositionend');}
function flush(){while(timers.length)timers.shift()();}
function unchanged(){assert.equal(url.hash,'#price-info-qa');assert.equal(stored,'preserved');assert.equal(storageAccess,0);}
input.focus();
'''


@unittest.skipUnless(shutil.which("node"), "Node.jsが必要")
class HubCompositionRecoveryTests(unittest.TestCase):
    def run_case(self, assertions):
        result = subprocess.run(["node", "-e", HARNESS + assertions, json.dumps(SCRIPT)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_committed_text_without_trailing_input_recovers_visible_rows(self):
        self.run_case("""
dispatch('compositionstart');search('未確定');assert.deepEqual(visible(),[]);
end('仮想薬甲');flush();assert.deepEqual(visible(),[0]);
assert.equal(nodes.hubFilterCount.textContent,'1 / 3品目を表示');
assert.equal(nodes.hubFilterEmpty.hidden,true);assert.equal(document.activeElement,input);unchanged();
""")

    def test_cancel_to_previous_query_recovers_without_replacing_rows(self):
        self.run_case("""
search('仮想薬乙');const identity=[...rows];dispatch('compositionstart');search('未確定');
end('仮想薬乙');flush();assert.deepEqual(visible(),[1]);
assert.ok(rows.every((row,i)=>row===identity[i]));assert.equal(document.activeElement,input);unchanged();
""")

    def test_cancel_to_empty_keeps_price_filter_and_group_visibility(self):
        self.run_case("""
price.checked=true;price.handlers.change();search('未確定');
end('');flush();assert.equal(price.checked,true);assert.deepEqual(visible(),[0,1]);
assert.deepEqual(groups.map(group=>group.hidden),[false,false,true]);
assert.equal(nodes.hubFilterClear.disabled,false);unchanged();
""")

    def test_trailing_input_applies_once_before_recovery_timer(self):
        self.run_case("""
search('未確定');writes=0;end('仮想薬甲');dispatch('input');flush();
assert.deepEqual(visible(),[0]);assert.equal(writes,rows.length,'one idempotent final filter pass');unchanged();
""")

    def test_clear_after_end_wins_over_pending_recovery(self):
        self.run_case("""
price.checked=true;price.handlers.change();search('未確定');end('仮想薬甲');
nodes.hubFilterClear.handlers.click();writes=0;flush();
assert.equal(input.value,'');assert.equal(price.checked,false);assert.deepEqual(visible(),[0,1,2]);
assert.equal(writes,0);assert.equal(document.activeElement,input);unchanged();
""")

    def test_recovery_uses_existing_safe_failure_fallback(self):
        self.run_case("""
search('未確定');vm.runInContext('String.prototype.normalize=undefined',context);
end('仮想薬甲');flush();assert.deepEqual(visible(),[0,1,2]);
assert.equal(nodes.hubFilter.hidden,true);assert.equal(nodes.hubFilterEmpty.hidden,true);unchanged();
""")


if __name__ == "__main__":
    unittest.main()
