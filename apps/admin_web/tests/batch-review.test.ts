import {webcrypto} from 'node:crypto'
import { mount,flushPromises } from '@vue/test-utils'
import {it,expect,vi,beforeEach} from 'vitest'
import {createMemoryHistory,createRouter} from 'vue-router'
import BatchReviewView from '../src/views/BatchReviewView.vue'
import * as api from '../src/api/admin'
import {detail,ME} from './fixtures'
import {setSession} from '../src/session'
vi.mock('../src/api/admin',()=>({getQuestion:vi.fn(),reviewQuestionBatch:vi.fn()}))
beforeEach(()=>{vi.resetAllMocks();sessionStorage.clear();localStorage.clear();vi.stubGlobal('crypto',webcrypto);const tails=new Map<string,Promise<unknown>>();Object.defineProperty(navigator,'locks',{configurable:true,value:{request:async<T>(name:string,_:unknown,action:()=>Promise<T>)=>{const next=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(action);tails.set(name,next);return next}}});setSession({token:'t',userId:ME,role:'reviewer'});vi.mocked(api.getQuestion).mockResolvedValue(detail())})
async function page(){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:BatchReviewView},{path:'/questions/:id',name:'question',component:{template:'<p />'}}]});await router.push('/?ids='+detail().id);await router.isReady();const w=mount(BatchReviewView,{global:{plugins:[router]}});await flushPromises();return w}
it('没有逐题明确确认不能批量审核，失败重试复用原键及body',async()=>{
 const w=await page();await w.get('[data-testid=batch-submit]').trigger('click');expect(api.reviewQuestionBatch).not.toHaveBeenCalled()
 await w.get('[data-testid=batch-confirm]').setValue(true)
 vi.mocked(api.reviewQuestionBatch).mockRejectedValue(new Error('网络中断'))
 await w.get('[data-testid=batch-submit]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestionBatch).toHaveBeenCalledTimes(1))
 const first=vi.mocked(api.reviewQuestionBatch).mock.calls[0]!
 await vi.waitFor(()=>expect(w.get('[data-testid=batch-submit]').attributes('disabled')).toBeUndefined())
 await w.get('[data-testid=batch-submit]').trigger('click');await vi.waitFor(()=>expect(api.reviewQuestionBatch).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.reviewQuestionBatch).mock.calls[1]).toEqual(first)
 expect(first[1].items[0]?.confirmed).toBe(true)
 w.unmount()
})

it('刷新恢复不确定批次的原修订和幂等键，隔离其他账号存储',async()=>{
 const body={items:[{question_id:detail().id,expected_version:1,decision:'approve' as const,confirmed:true as const}]}
 sessionStorage.setItem(`batch-review:${ME}`,JSON.stringify({body,key:'persisted-batch-key',expires:Date.now()+60000}))
 sessionStorage.setItem('batch-review:other','other-account-data')
 vi.mocked(api.reviewQuestionBatch).mockRejectedValue(new Error('offline'))
 const w=await page();await w.get('[data-testid=batch-submit]').trigger('click');await flushPromises()
 expect(api.reviewQuestionBatch).not.toHaveBeenCalled()
 expect(sessionStorage.getItem(`batch-review:${ME}`)).toBe(JSON.stringify({body,key:'persisted-batch-key',expires:JSON.parse(sessionStorage.getItem(`batch-review:${ME}`)!).expires}))
 vi.spyOn(window,'confirm').mockReturnValue(true)
 await w.get('[data-testid=batch-abandon]').trigger('click');await vi.waitFor(()=>expect(w.find('[data-testid=batch-abandon]').exists()).toBe(false))
 await w.get('[data-testid=batch-confirm]').setValue(true)
 await w.get('[data-testid=batch-submit]').trigger('click')
 await vi.waitFor(()=>expect(api.reviewQuestionBatch).toHaveBeenCalledTimes(1))
 const sent=vi.mocked(api.reviewQuestionBatch).mock.calls[0]!
 expect(sent[2]).not.toBe('persisted-batch-key');expect(sent[1].items[0]?.expected_review_revision).toBe(detail().review_revision)
 expect(JSON.parse(sessionStorage.getItem(`batch-review:${ME}`)!).body).toEqual(body)
 expect(sessionStorage.getItem('batch-review:other')).toBe('other-account-data')
 w.unmount()
})
it('明确成功的结果刷新后继续保留，避免自动重审',async()=>{
 sessionStorage.setItem(`batch-review:${ME}:result`,JSON.stringify({expires:Date.now()+60000,value:{items:[{question_id:detail().id,status:'succeeded',state:null,error:null}]}}))
 const w=await page()
 expect(w.get<HTMLInputElement>('[data-testid=batch-confirm]').element.disabled || w.get('[data-testid=batch-confirm]').attributes('disabled')!==undefined || w.get('fieldset').attributes('disabled')!==undefined).toBe(true)
 await w.get('[data-testid=batch-submit]').trigger('click');expect(api.reviewQuestionBatch).not.toHaveBeenCalled()
 w.unmount()
})
