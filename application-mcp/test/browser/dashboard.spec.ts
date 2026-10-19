import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import path from 'node:path';

test('workspace resumes a pending checkpoint, prevents duplicate starts and remembers themes',async({page},info)=>{
  let resumed='';
  let queued:any;
  let running:string|null=null;
  const apps:any[]=[
    {id:'current',input:{company:'Current Employer',title:'Analyst',jobUrl:'https://current.example/job'},state:'paused',reason:'CAPTCHA: complete it in Chrome.',documents:[{kind:'resume',name:'tailored.pdf',attached:true}],snapshot:{url:'https://current.example/application/step2',fields:[],buttons:[],blockers:['CAPTCHA']},updatedAt:'2026-10-17T21:00:00Z',evidence:[{kind:'review',at:'now'}]},
    {id:'saved',input:{company:'Saved Employer',title:'Data Engineer',jobUrl:'https://saved.example/job'},state:'paused',reason:'Required blank: source',documents:[],deferredAt:'2026-10-17T20:00:00Z',snapshot:{url:'https://saved.example/application/step3',fields:[],buttons:[],blockers:[]},updatedAt:'2026-10-17T20:00:00Z'}
  ];
  await page.route('http://workspace.test/**',async route=>{
    const url=new URL(route.request().url());
    if(['/','/dashboard.js','/dashboard.css'].includes(url.pathname)){
      const filename=url.pathname==='/'?'index.html':url.pathname.slice(1);
      return route.fulfill({body:await readFile(path.resolve('public',filename)),contentType:filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html'});
    }
    if(url.pathname==='/health')return route.fulfill({json:{chromeConnected:true,extensionConfigured:true,running}});
    if(url.pathname==='/queue'){if(route.request().method()==='POST')queued=route.request().postDataJSON();return route.fulfill({json:{enabled:true,message:'Preparing outdated message'}});}
    if(url.pathname==='/applications')return route.fulfill({json:apps});
    if(url.pathname.endsWith('/history'))return route.fulfill({json:{events:[]}});
    if(url.pathname==='/notifications')return route.fulfill({json:{barriers:[],settings:{}}});
    if(url.pathname==='/candidates')return route.fulfill({json:{candidates:[{key_id:'saved-job',run_id:'run',company:'Saved Employer',title:'Data Engineer',apply_url:'https://saved.example/job'},{key_id:'new-job',run_id:'run2',company:'New Employer',title:'Developer',apply_url:'https://new.example/job'},{company:'Canada Life',title:'Excluded',apply_url:'https://excluded.example'}]}});
    if(url.pathname==='/applications/current/cancel'){apps[0].state='rejected';apps[0].cancelledAt='now';delete apps[0].deferredAt;return route.fulfill({json:apps[0]});}
    if(url.pathname==='/applications/saved/restart'){
      expect(route.request().postDataJSON()).toEqual({userConfirmed:true});apps[1].state='paused';apps[1].linkHealth='session_expired';return route.fulfill({json:apps[1]});
    }
    if(url.pathname==='/applications/saved/manual-confirmation'){
      expect(route.request().postDataJSON()).toMatchObject({userConfirmed:true,tabClosed:true});
      apps[1].state='submitted';apps[1].verificationSource='user_confirmation';apps[1].reason='Submitted — manually confirmed by you.';apps[1].synced=true;running=null;
      return route.fulfill({json:apps[1]});
    }
    if(url.pathname==='/applications/saved/resume-checkpoint'){
      resumed='saved';apps[0].deferredAt='2026-10-17T21:30:00Z';delete apps[1].deferredAt;apps[1].state='working';apps[1].reason='';running='saved';
      return route.fulfill({json:apps[1]});
    }
    return route.fulfill({status:404,json:{error:'Unexpected test request: '+url.pathname}});
  });
  await page.goto('http://workspace.test/');
  await expect(page.locator('#count-pending')).toHaveText('1');
  await expect(page.locator('#queue-status')).toContainText('Current Employer: CAPTCHA');
  await expect(page.locator('#pending-questions')).toContainText('application/step3');
  await expect(page.getByRole('button',{name:'Start in Chrome',exact:true})).toBeDisabled();
  await expect(page.locator('#candidates')).not.toContainText('Canada Life');
  await page.getByLabel('Theme',{exact:true}).selectOption('light');
  await page.screenshot({path:info.outputPath('workspace-light.png'),fullPage:true});
  await page.getByLabel('Theme',{exact:true}).selectOption('dark');
  await expect(page.locator('#queue')).toHaveCSS('background-color','rgb(18, 28, 44)');
  await page.screenshot({path:info.outputPath('workspace-dark.png'),fullPage:true});
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.locator('[data-application-id="saved"]').getByRole('button',{name:'Save current & resume this',exact:true}).click();
  expect(resumed).toBe('saved');
  await expect(page.locator('#current')).toContainText('Saved Employer');
  await expect(page.locator('#current')).toContainText('application/step3');
  await expect(page.locator('#pending-questions')).toContainText('Current Employer');
  await page.locator('#current').getByRole('button',{name:'Restart from original link',exact:true}).click();
  await expect(page.locator('#current')).toContainText('saved session or link expired');
  await page.locator('#current').getByText('Confirm submitted manually — tab closed',{exact:true}).click();
  await expect(page.getByRole('button',{name:'Confirm manual submission',exact:true})).toBeDisabled();
  await page.getByRole('checkbox',{name:/I personally submitted Saved Employer/}).check();
  await page.getByRole('button',{name:'Confirm manual submission',exact:true}).click();
  await expect(page.locator('#current')).toContainText('Submitted · manually confirmed');
  await expect(page.locator('#count-submitted')).toHaveText('1');
  await page.locator('#application-list [data-application-id=current]').getByRole('button',{name:'Cancel automation',exact:true}).click();
  await expect(page.locator('#application-list')).toContainText('Cancelled by you');
  await page.locator('#application-filter').selectOption('cancelled');
  await expect(page.locator('#application-list tbody tr')).toHaveCount(1);
  await expect(page.locator('#application-list')).not.toContainText('Saved Employer');
  await page.locator('#scope-indeed').click();
  await expect(page.locator('#candidates')).not.toContainText('New Employer');
  await expect(page.locator('#scope-description')).toContainText('Easy Apply availability');
  await page.getByRole('button',{name:'Run Indeed queue',exact:true}).click();
  expect(queued).toMatchObject({enabled:true,scope:'indeed'});
  await page.locator('#scope-company').click();
  await expect(page.locator('#candidates')).toContainText('New Employer');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
