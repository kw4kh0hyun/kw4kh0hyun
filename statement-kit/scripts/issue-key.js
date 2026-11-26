// Manually issue a Pro key (refunds, support, giveaways):
//   LICENSE_SECRET=... npm run issue-key -- someone@example.com 30
import { issueKey } from '../lib/license.js';

const [email = 'manual', days = '30'] = process.argv.slice(2);
console.log(issueKey(process.env.LICENSE_SECRET, { email, days: Number(days) }));
