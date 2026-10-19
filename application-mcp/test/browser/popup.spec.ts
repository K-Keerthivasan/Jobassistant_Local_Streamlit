import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import path from 'node:path';

test('extension questions save exact answers with explicit reuse and themes persist',async({page},info)=>{
  let saved:any;
  let questions:any[]=[{applicationId:'pending',company:'Example Employer',title:'Engineer',deferred:true,reason:'Required blank',mayOmitCover:false,
    questions:[{selector:'#source',frameId:0,question:'How did you hear about us?',options:['Indeed','Referral'],manual:false},
    {selector:'#consent',frameId:0,question:'I agree to terms',options:[],manual:true}]}];
  await page.addInitScript(()=>{
    (globalThis as any).chrome={runtime:{sendMessage:async()=>({id:'fixture',connected:true})},storage:{local:{
      get:async(key:string)=>({[key]:localStorage.getItem(key)}),
      set:async(data:any)=>{for(const [key,value]of Object.entries(data))localStorage.setItem(key,String(value));}
    }}};
  });
  await page.route('http://popup.test/**',async route=>{
    const name=new URL(route.request().url()).pathname.slice(1)||'popup.html';
    const file=await readFile(path.resolve('extension',name));
    await route.fulfill({body:file,contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('http://127.0.0.1:8091/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/questions/answer'){
      saved=route.request().postDataJSON();questions=[];
      return route.fulfill({json:{saved:true}});
    }
    if(url.pathname==='/questions/blank'){saved=route.request().postDataJSON();questions=[];return route.fulfill({json:{saved:true}});}
    if(url.pathname==='/questions/watch'){saved=route.request().postDataJSON();questions[0].questions[0].watching=true;return route.fulfill({json:{watching:true}});}
    return route.fulfill({json:url.pathname==='/questions'?questions:{}});
  });
  await page.goto('http://popup.test/popup.html');
  await expect(page.locator('#question-count')).toHaveText('2');
  await expect(page.getByText('Complete this choice personally')).toBeVisible();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.getByLabel('Theme',{exact:true}).selectOption('light');
  await page.screenshot({path:info.outputPath('questions-light.png'),fullPage:true});
  await page.getByLabel('Theme',{exact:true}).selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.screenshot({path:info.outputPath('questions-dark.png'),fullPage:true});
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.getByLabel('How did you hear about us?',{exact:true}).selectOption('Indeed');
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Confirm answer',exact:true}).click();
  await expect(page.locator('#questions-status')).toContainText('Answer saved');
  expect(saved).toMatchObject({applicationId:'pending',answer:'Indeed',reuse:true,userConfirmed:true});
  await expect(page.locator('#question-count')).toHaveText('0');
  questions=[{applicationId:'pending',company:'Example Employer',title:'Engineer',deferred:true,questions:[{selector:'#middle',frameId:0,question:'Middle Name',options:[],manual:false,canLeaveBlank:true}]}];
  await page.reload();
  await expect(page.getByRole('button',{name:'Leave blank',exact:true})).toBeVisible();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('button',{name:'Leave blank',exact:true}).click();
  expect(saved).toMatchObject({selector:'#middle',reuse:false,userConfirmed:true});
  await expect(page.locator('#question-count')).toHaveText('0');
  questions=[{applicationId:'pending',company:'Example Employer',title:'Engineer',deferred:false,questions:[{selector:'#supervisor',frameId:0,question:'Supervisor',options:[],manual:false}]}];
  await page.reload();await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'I’ll fill this in Chrome',exact:true}).click();
  expect(saved).toMatchObject({selector:'#supervisor',reuse:true,userConfirmed:true});
  await expect(page.getByRole('button',{name:'Watching for your entry in Chrome',exact:true})).toBeDisabled();
});
