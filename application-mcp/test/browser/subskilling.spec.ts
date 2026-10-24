import {test,expect} from '@playwright/test';
test.skip(!process.env.LIVE_STUDIO, 'Requires deployed Studio');
test('live subskilling view shows persistent audit and learning defaults',async({page})=>{
 await page.goto('http://127.0.0.1:8088/');
 await page.getByRole('button',{name:'Skill subskilling',exact:true}).click();
 await expect(page.locator('#ss-progress')).toContainText('queued');
 await expect(page.locator('#ss-state')).toHaveValue('learning');
 await expect(page.locator('#ss-confirm')).not.toBeChecked();
 await expect(page.locator('#ss-jobs details').first()).toBeVisible();
 await expect(page.locator('a[target="_blank"][href*="/download/"]')).toHaveCount(0);
});
