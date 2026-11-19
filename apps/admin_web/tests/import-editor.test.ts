import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import QuestionEditor from '../src/components/QuestionEditor.vue'
import { detail, experimentDetail, proofDetail, writtenDetail } from './fixtures'
function fillDetail() {
  const source = detail({answer_mode:'fill',type:'fill_blank'})
  source.content = {...source.content,options:[],blanks:[{key:'b1',label:null,unit_hint:null,placeholder:null}]}
  source.answer = {value:{b1:'5'},equivalence_rules:{b1:{type:'numeric',rel_tol:0.001}} as unknown as Record<string,never>,units:{b1:{required:true,accepted:['m/s²']}} as unknown as Record<string,never>}
  return source
}
import type { AdminQuestionDetail, AdminQuestionEdit } from '../src/api/types'
import * as api from '../src/api/admin'
vi.mock('../src/api/admin', () => ({ createQuestionVersion: vi.fn() }))
function latest(wrapper: ReturnType<typeof mount>): AdminQuestionEdit {
  const events = wrapper.emitted('draft')!
  return events[events.length - 1]![1] as AdminQuestionEdit
}
it.each([['choice',detail()],['fill',fillDetail()],['written',writtenDetail()],['proof',proofDetail()],['experiment',experimentDetail()]] as const)('本机%s编辑沿用题型语义且不调用版本API', async (_, source: AdminQuestionDetail) => {
  const wrapper = mount(QuestionEditor, { props: { detail: source, localOnly: true } })
  await wrapper.get('[data-testid=title]').setValue(source.title + ' 校对')
  await flushPromises()
  expect(latest(wrapper).title).toBe(source.title + ' 校对')
  expect(wrapper.find('[data-testid=save]').exists()).toBe(false)
  expect(api.createQuestionVersion).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('参考证明保留阶段、依据和自查点；实验安全与表格保持既有规则', async () => {
  const proof = mount(QuestionEditor, { props: { detail: proofDetail(), localOnly:true } })
  await proof.get('[data-testid=step-reason-0]').setValue('人工核对依据')
  expect((latest(proof).answer.value as {steps:Array<{reason:string}>}).steps[0]!.reason).toBe('人工核对依据')
  expect(latest(proof).rubric).toHaveProperty('points')
  proof.unmount()
  const experiment = mount(QuestionEditor, {props:{detail:experimentDetail(),localOnly:true}})
  expect(experiment.text()).toContain('高风险的实验现在不收录')
  await experiment.get('[data-testid=title]').setValue('人工校对实验')
  expect(latest(experiment).content.data_tables).toEqual(experimentDetail().content.data_tables)
  expect(latest(experiment).content.safety).toEqual(experimentDetail().content.safety)
  experiment.unmount()
})
it('填空等价判定和单位别名可视化编辑，仍保留JSON', async () => {
  const wrapper = mount(QuestionEditor, {props:{detail:fillDetail(),localOnly:true}})
  await wrapper.get('[data-testid=blank-rel-tol-0]').setValue('0.02')
  await wrapper.get('[data-testid=blank-unit-aliases-0]').setValue('m/s²,米每二次方秒')
  expect(latest(wrapper).answer.equivalence_rules).toMatchObject({b1:{type:'numeric',rel_tol:0.02}})
  expect(latest(wrapper).answer.units).toMatchObject({b1:{accepted:['m/s²','米每二次方秒']}})
  wrapper.unmount()
})

it('选择题答案、分层提示和标准解析同步为同一请求', async () => {
  const wrapper = mount(QuestionEditor, {props:{detail:detail(),localOnly:true}})
  await wrapper.get('[data-testid=option-correct-0]').setValue(true)
  await wrapper.get('[data-testid=standard-final]').setValue('人工校对的标准答案')
  await wrapper.get('[aria-label="分层提示（由浅到深，不能泄露答案） 1"]').setValue('先核对题目条件')
  expect(latest(wrapper).answer.value).toContain('A')
  expect(latest(wrapper).solutions.find(s => s.kind === 'standard')?.final_answer).toBe('人工校对的标准答案')
  expect(latest(wrapper).teaching.hints[0]).toBe('先核对题目条件')
  wrapper.unmount()
})
