import {createRouter,createMemoryHistory} from 'vue-router'
import QuestionView from '../src/views/QuestionView.vue'
import { webcrypto } from 'node:crypto'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach,beforeEach,expect,it,vi } from 'vitest'
import QuestionEditor from '../src/components/QuestionEditor.vue'
import DecisionPanel from '../src/components/DecisionPanel.vue'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import { setSession } from '../src/session'
import { detail,ME } from './fixtures'
vi.mock('../src/api/admin',()=>({createQuestionVersion:vi.fn(),reviewQuestion:vi.fn(),getQuestion:vi.fn()}))
enableAutoUnmount(afterEach)
beforeEach(()=>{localStorage.clear();vi.resetAllMocks();vi.stubGlobal('crypto',webcrypto);const tails=new Map<string,Promise<unknown>>();Object.defineProperty(navigator,'locks',{configurable:true,value:{request:<T>(name:string,_options:unknown,action:()=>Promise<T>)=>{const p=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(action);tails.set(name,p);return p}}});setSession({token:'tok',userId:ME,role:'reviewer'})})
it('编辑A未知重载不自动HTTP且明确恢复原body/key双CAS',async()=>{
 vi.mocked(api.createQuestionVersion).mockRejectedValue(new ApiError(0,'network_error','断网'))
 const first=mount(QuestionEditor,{props:{detail:detail({review_revision:7})}})
 await flushPromises();await first.get('[data-testid=title]').setValue('编辑A');await vi.waitFor(()=>expect(first.get('[data-testid=save]').attributes('disabled')).toBeUndefined());await first.get('[data-testid=save]').trigger('click');
 await vi.waitFor(()=>expect(api.createQuestionVersion).toHaveBeenCalledTimes(1));const original=vi.mocked(api.createQuestionVersion).mock.calls[0]!
 first.unmount();const next=mount(QuestionEditor,{props:{detail:detail({version:3,review_revision:9})}})
 await vi.waitFor(()=>expect(next.find('[data-testid=edit-retry]').exists()).toBe(true));expect(api.createQuestionVersion).toHaveBeenCalledTimes(1)
 await next.get('[data-testid=edit-retry]').trigger('click');await vi.waitFor(()=>expect(api.createQuestionVersion).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.createQuestionVersion).mock.calls[1]).toEqual(original);expect(original[2]).toMatchObject({expected_version:1,expected_review_revision:7})
})
it('审核A未知刷新到withdrawn普通决策禁用时仍有原操作恢复',async()=>{
 vi.mocked(api.reviewQuestion).mockRejectedValue(new ApiError(0,'network_error','断网'))
 const first=mount(DecisionPanel,{props:{detail:detail({review_revision:7})}})
 await flushPromises();await vi.waitFor(()=>expect(first.get('[data-testid=submit-decision]').attributes('disabled')).toBeUndefined());await first.get('[data-testid=submit-decision]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestion).toHaveBeenCalledTimes(1));const original=vi.mocked(api.reviewQuestion).mock.calls[0]!
 first.unmount();const next=mount(DecisionPanel,{props:{detail:detail({status:'withdrawn',review_revision:9})}})
 await vi.waitFor(()=>expect(next.find('[data-testid=review-retry]').exists()).toBe(true))
 await next.get('[data-testid=review-retry]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestion).toHaveBeenCalledTimes(2));expect(vi.mocked(api.reviewQuestion).mock.calls[1]).toEqual(original)
})




it('编辑A在途B本机续改，A成功不emit清除B且重载B保留',async()=>{
 let release!:(v:ReturnType<typeof detail>)=>void;vi.mocked(api.createQuestionVersion).mockImplementation(()=>new Promise(resolve=>release=resolve))
 const w=mount(QuestionEditor,{props:{detail:detail({review_revision:7})}});await flushPromises();await w.get('[data-testid=title]').setValue('A')
 await vi.waitFor(()=>expect(w.get('[data-testid=save]').attributes('disabled')).toBeUndefined());await w.get('[data-testid=save]').trigger('click');await vi.waitFor(()=>expect(api.createQuestionVersion).toHaveBeenCalledTimes(1))
 await w.get('[data-testid=title]').setValue('B');release(detail({version:2,review_revision:8}));await vi.waitFor(()=>expect(w.text()).toContain('历史写入结果'))
 expect(w.emitted('saved')).toBeUndefined();expect((w.get('[data-testid=title]').element as HTMLInputElement).value).toBe('B');w.unmount()
 const restored=mount(QuestionEditor,{props:{detail:detail({version:3,review_revision:9})}});await vi.waitFor(()=>expect((restored.get('[data-testid=title]').element as HTMLInputElement).value).toBe('B'))
 expect(restored.get('[data-testid=save]').attributes('disabled')).toBeDefined()
})
it('两个tab表单分支B落盘，载入不隐式采用新来源',async()=>{
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const a=new QuestionWriteRecovery(ME,'question-a','edit'),b=new QuestionWriteRecovery(ME,'question-a','edit')
 const old=await b.load();await a.save('A',old.generation);await b.save('B',old.generation)
 const restored=await new QuestionWriteRecovery(ME,'question-a','edit').load();expect(restored.raw).toBe('A');expect(restored.branches.some(v=>v.raw==='B')).toBe(true)
 await a.save('C',restored.generation);await expect(b.promoteBranch(restored.branches[0]!.id,restored.generation)).rejects.toThrow('变化')
})
it('result_known可无HTTP确认且严格筛owner/resource/method/path',async()=>{
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const d=detail();const a=new QuestionWriteRecovery(ME,d.id,'edit'),other=new QuestionWriteRecovery(ME,'other','edit')
 const unrelated=await a.commands.prepare({key:'foreign-key',method:'POST',path:other.path,resource:other.resource,body:{expected_version:1,expected_review_revision:1}});expect(await a.pending()).toBeUndefined()
 const command=await a.commands.prepare({key:'edit-known',method:'POST',path:a.path,resource:a.resource,body:{expected_version:1,expected_review_revision:1}});await a.commands.recordResult(command,detail() as never)
 const w=mount(QuestionEditor,{props:{detail:d}});await vi.waitFor(()=>expect(w.find('[data-testid=edit-ack]').exists()).toBe(true));await w.get('[data-testid=edit-ack]').trigger('click');await vi.waitFor(()=>expect(w.find('[data-testid=edit-ack]').exists()).toBe(false));expect(api.createQuestionVersion).not.toHaveBeenCalled();expect((await other.pending())?.key).toBe(unrelated.key)
})

it('存储配额拒绝时保留编辑且零API',async()=>{
 const w=mount(QuestionEditor,{props:{detail:detail()}});await flushPromises()
 const original=Storage.prototype.setItem;const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k.startsWith('admin-question-draft/'))throw Error('quota');original.call(this,k,v)})
 await w.get('[data-testid=title]').setValue('仅内存B');await vi.waitFor(()=>expect(w.text()).toContain('仅在当前页面内存'));expect(api.createQuestionVersion).not.toHaveBeenCalled();expect((w.get('[data-testid=title]').element as HTMLInputElement).value).toBe('仅内存B');spy.mockRestore()
})
it('损坏draft原文保留并阻止发送',async()=>{
 const d=detail(),key=`admin-question-draft/v1/${encodeURIComponent(ME)}/${encodeURIComponent(d.id)}/edit`,raw='{"v":99,"precious":"input"}';localStorage.setItem(key,raw)
 const w=mount(QuestionEditor,{props:{detail:d}});await flushPromises();await w.get('[data-testid=title]').setValue('B');expect(w.get('[data-testid=save]').attributes('disabled')).toBeDefined();expect(api.createQuestionVersion).not.toHaveBeenCalled();expect(localStorage.getItem(key)).toBe(raw)
})
it('审核422持久rejected后修正新意图，网络失败仍保留原键',async()=>{
 vi.mocked(api.reviewQuestion).mockRejectedValueOnce(new ApiError(422,'validation_error','校验拒绝')).mockRejectedValue(new ApiError(0,'network_error','断网'))
 const w=mount(DecisionPanel,{props:{detail:detail()}});await flushPromises();await vi.waitFor(()=>expect(w.get('[data-testid=submit-decision]').attributes('disabled')).toBeUndefined());await w.get('[data-testid=submit-decision]').trigger('click');await vi.waitFor(()=>expect(w.text()).toContain('校验拒绝'))
 await w.get('[data-testid=comment]').setValue('修正B');await w.get('[data-testid=submit-decision]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestion).toHaveBeenCalledTimes(2));expect(vi.mocked(api.reviewQuestion).mock.calls[0]?.[3]).not.toBe(vi.mocked(api.reviewQuestion).mock.calls[1]?.[3])
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const commands=await new QuestionWriteRecovery(ME,detail().id,'review').commands.list();expect(commands[0]?.phase).toBe('rejected');expect(commands[1]?.body.comment).toBe('修正B')
})
async function questionPage(id:string){
 const router=createRouter({history:createMemoryHistory(),routes:[{name:'question',path:'/questions/:id',component:QuestionView},{name:'queue',path:'/',component:{template:'<div/>'}},{name:'compare',path:'/compare/:id',component:{template:'<div/>'}}]});await router.push(`/questions/${id}`);await router.isReady()
 const w=mount(QuestionView,{global:{plugins:[router],stubs:{DecisionPanel:true,MediaAttachments:true}}});return {w,router}
}
it('题目GET A迟到不得覆盖新资源B',async()=>{
 const a=detail();let release!:(d:ReturnType<typeof detail>)=>void
 vi.mocked(api.getQuestion).mockImplementation((_token,id)=>id===a.id?new Promise(resolve=>release=resolve):Promise.resolve(detail({id:'resource-b',title:'当前B'})))
 const {w,router}=await questionPage(a.id);await vi.waitFor(()=>expect(api.getQuestion).toHaveBeenCalledTimes(1));await router.push('/questions/resource-b');await vi.waitFor(()=>expect(w.get('h1').text()).toBe('当前B'))
 release(a);await flushPromises();expect(w.get('h1').text()).toBe('当前B')
})
it('已发布当前v3仍可纯本机ACK旧v2，不回退GET当前资源',async()=>{
 const d=detail({version:3,review_revision:9,status:'published',title:'当前v3'});vi.mocked(api.getQuestion).mockResolvedValue(d)
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const s=new QuestionWriteRecovery(ME,d.id,'edit')
 const c=await s.commands.prepare({key:'old-editor',method:'POST',path:s.path,resource:s.resource,body:{expected_version:1,expected_review_revision:7}});await s.commands.recordResult(c,detail({version:2}) as never)
 const {w}=await questionPage(d.id);await vi.waitFor(()=>expect(w.find('[data-testid=question-history-ack]').exists()).toBe(true));expect(w.get('[data-testid=edit]').attributes('disabled')).toBeDefined()
 await w.get('[data-testid=question-history-ack]').trigger('click');await vi.waitFor(()=>expect(w.find('[data-testid=question-history-ack]').exists()).toBe(false));expect(w.get('h1').text()).toBe('当前v3');expect(api.createQuestionVersion).not.toHaveBeenCalled()
})
it('当前题页恢复收到明确422后先落rejected，不循环未知',async()=>{
 const d=detail({status:'published'});vi.mocked(api.getQuestion).mockResolvedValue(d);vi.mocked(api.createQuestionVersion).mockRejectedValue(new ApiError(422,'validation_error','校验拒绝'))
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const s=new QuestionWriteRecovery(ME,d.id,'edit');await s.commands.prepare({key:'old-reject',method:'POST',path:s.path,resource:s.resource,body:{expected_version:1,expected_review_revision:1}})
 const {w}=await questionPage(d.id);await vi.waitFor(()=>expect(w.find('[data-testid=question-history-retry]').exists()).toBe(true));await w.get('[data-testid=question-history-retry]').trigger('click');await vi.waitFor(()=>expect(w.find('[data-testid=question-history-retry]').exists()).toBe(false));expect((await s.commands.list())[0]?.phase).toBe('rejected')
})
it('旧B成功与最新C配额失败后不得用分支D覆盖仅内存C',async()=>{
 const {defineComponent,ref,watch,nextTick,h}=await import('vue')
 const {QuestionWriteRecovery,useQuestionCommands}=await import('../src/question-write-recovery')
 const source={id:'serial-question',version:1,reviewRevision:1}
 const store=new QuestionWriteRecovery(ME,source.id,'edit')
 const envelope=(title:string)=>JSON.stringify({source,form:{title}})
 await store.save(envelope('A'),0);await store.save(envelope('D'),0)
 const d=(await store.load()).branches.find(b=>JSON.parse(b.raw).form.title==='D')!
 let form!:import('vue').Ref<{title:string}>,recovery!:ReturnType<typeof useQuestionCommands>
 const w=mount(defineComponent({setup(){form=ref({title:'A'});recovery=useQuestionCommands('edit',source,()=>({...form.value}),v=>{form.value=v as {title:string}});watch(form,()=>recovery.changed(),{deep:true});return ()=>h('div',form.value.title)}}))
 await vi.waitFor(()=>expect(recovery.loaded.value).toBe(true))
 const previous=navigator.locks.request.bind(navigator.locks)
 let release!:()=>void,entered!:()=>void;const enteredPromise=new Promise<void>(resolve=>entered=resolve),gate=new Promise<void>(resolve=>release=resolve);let delayed=false
 Object.defineProperty(navigator,'locks',{configurable:true,value:{request:(name:string,options:unknown,action:()=>Promise<unknown>)=>previous(name,options as LockOptions,async()=>{if(!delayed&&name.startsWith('admin-question-draft/')){delayed=true;entered();await gate}return action()})}})
 const original=Storage.prototype.setItem;const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k.startsWith('admin-question-draft/')){const raw=JSON.parse(v).raw;if(JSON.parse(raw).form.title==='C')throw Error('quota-C')}original.call(this,k,v)})
 form.value.title='B';await nextTick();await enteredPromise
 form.value.title='C';await nextTick();release()
 await vi.waitFor(()=>expect(recovery.message.value).toContain('仅在当前页面内存'))
 await recovery.loadBranch(d.id)
 expect(form.value.title).toBe('C');expect(w.text()).toBe('C');spy.mockRestore()
})
it('同raw和来源重复保存不增generation或制造重复分支',async()=>{
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const s=new QuestionWriteRecovery(ME,'dedupe-question','edit')
 const a=await s.save('same-source-A',0);const duplicate=await s.save('same-source-A',a.generation);expect(duplicate.generation).toBe(a.generation)
 await s.save('head-C',a.generation);const conflict=await s.save('branch-B',a.generation)
 for(let n=0;n<223;n++)await s.save('branch-B',a.generation)
 const restored=await s.load();expect(restored.generation).toBe(conflict.generation);expect(restored.branches.filter(b=>b.raw==='branch-B')).toHaveLength(1)
})
it('409后明确保留旧unknown并采用新来源，修正B才可新key发送',async()=>{
 vi.mocked(api.reviewQuestion).mockRejectedValueOnce(new ApiError(409,'review_revision_conflict','审核来源冲突')).mockRejectedValue(new ApiError(0,'network_error','断网'))
 const first=mount(DecisionPanel,{props:{detail:detail({review_revision:7})}});await flushPromises();await vi.waitFor(()=>expect(first.get('[data-testid=submit-decision]').attributes('disabled')).toBeUndefined());await first.get('[data-testid=submit-decision]').trigger('click');await vi.waitFor(()=>expect(first.text()).toContain('审核来源冲突'));const old=vi.mocked(api.reviewQuestion).mock.calls[0]!
 first.unmount();const next=mount(DecisionPanel,{props:{detail:detail({review_revision:8})}});await vi.waitFor(()=>expect(next.find('[data-testid=review-release]').exists()).toBe(true));await next.get('[data-testid=review-release]').trigger('click');await vi.waitFor(()=>expect(next.find('[data-testid=review-retry]').exists()).toBe(false));await next.get('[data-testid=review-adopt]').trigger('click');await vi.waitFor(()=>expect(next.find('[data-testid=review-adopt]').exists()).toBe(false));await next.get('[data-testid=comment]').setValue('新来源B');await next.get('[data-testid=submit-decision]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestion).toHaveBeenCalledTimes(2))
 const newer=vi.mocked(api.reviewQuestion).mock.calls[1]!;expect(newer[2].expected_review_revision).toBe(8);expect(newer[3]).not.toBe(old[3]);const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const rows=await new QuestionWriteRecovery(ME,detail().id,'review').commands.list();expect(rows[0]?.phase).toBe('prepared');expect(rows[0]?.body.expected_review_revision).toBe(7)
})
it('释放落盘失败保留原lane；晚到known历史不复活，known不可放弃',async()=>{
 const {QuestionWriteRecovery}=await import('../src/question-write-recovery');const d=detail(),s=new QuestionWriteRecovery(ME,d.id,'edit')
 const c=await s.commands.prepare({key:'release-old',method:'POST',path:s.path,resource:s.resource,body:{expected_version:1,expected_review_revision:1}})
 const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k.startsWith('admin-question-draft/'))throw Error('quota');original.call(this,k,v)})
 await expect(s.releaseUnknown(c)).rejects.toThrow('quota');expect((await s.pending())?.key).toBe(c.key);spy.mockRestore()
 await s.releaseUnknown(c);await s.commands.recordResult(c,detail() as never);expect(await new QuestionWriteRecovery(ME,d.id,'edit').pending()).toBeUndefined()
 const newer=await s.commands.prepare({key:'new-known',method:'POST',path:s.path,resource:s.resource,body:{expected_version:3,expected_review_revision:3}});await s.commands.recordResult(newer,detail({version:4}) as never);await expect(s.releaseUnknown(newer)).rejects.toThrow('已知成功');expect((await s.pending())?.key).toBe(newer.key)
})

