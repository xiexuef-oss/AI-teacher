import { webcrypto } from 'node:crypto'
import { flushPromises } from '@vue/test-utils'
import { expect, vi } from 'vitest'
let pending=0
/** Explicit browser capability only for tests; production keeps Web Locks fail-closed. */
export function installBrowserStorage(){
 pending=0
 for(const key of Object.keys(localStorage)){if(key.startsWith('admin-question-draft/')||key.startsWith('admin-write/'))localStorage.removeItem(key)}
 vi.stubGlobal('crypto',webcrypto)
 const tails=new Map<string,Promise<unknown>>()
 Object.defineProperty(navigator,'locks',{configurable:true,value:{request:<T>(name:string,_options:unknown,action:()=>Promise<T>)=>{
  pending++
  const next=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(action)
  tails.set(name,next.then(()=>{},()=>{}))
  return next.finally(()=>{pending--})
 }}})
}
/** Wait for actual lock/storage/digest completion, not a fixed delay. */
export async function flushRecovery(){
 await flushPromises()
 await vi.waitFor(()=>expect(pending).toBe(0))
 await flushPromises()
 await vi.waitFor(()=>expect(pending).toBe(0))
}
