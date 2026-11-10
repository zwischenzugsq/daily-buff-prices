import copy, json, unittest
from pathlib import Path
import refresh as r

SEED=json.loads((Path(__file__).parent/'seed.json').read_text(encoding='utf-8'))
def report():return {'updated':0,'held':[],'newBranches':set()}
class Fake:
    def __init__(self,*responses):self.responses=iter(responses)
    def get(self,*args,**kwargs):return next(self.responses)

class RefreshTests(unittest.TestCase):
    def test_seed_unique_and_valid(self):r.validate(SEED,SEED);self.assertEqual(len(r.keyed(SEED['products'])),750)
    def test_no_new_food_or_shop(self):
        for field in ('foodId','sourceName','pack','barcode','sourceUrl'):
            book=copy.deepcopy(SEED);book['products'][0][field]='changed'
            with self.assertRaises(ValueError):r.validate(book,SEED)
        book=copy.deepcopy(SEED);book['shops'][0]['address']='changed'
        with self.assertRaises(ValueError):r.validate(book,SEED)
    def test_duplicate_branch_rejected(self):
        book=copy.deepcopy(SEED);book['products'][0]['prices']*=2
        with self.assertRaises(ValueError):r.validate(book,SEED)
    def test_invalid_or_suspicious_price(self):
        for value in (None,True,0,-1,float('nan'),float('inf'),1.234,100,.01):
            with self.assertRaises(ValueError):r.checked_price(value,2)
        self.assertEqual(r.checked_price(1.69,1.55),1.69)
    def test_alpha_exact_identity(self):
        p=copy.deepcopy(next(p for p in SEED['products'] if p['source']=='alphamega'))
        row={'uniqueId':p['sourceProductId'],'title':p['sourceName'],'barcode':p['barcode'],'currency':'EUR','productUrl':p['sourceUrl'],'price':p['prices'][0][1],'availability':'false'}
        for field,value in [('title','Different pack'),('barcode','5290000000000'),('currency','USD'),('productUrl','https://evil.example'),('availability','unknown')]:
            bad=dict(row);bad[field]=value
            with self.assertRaises(ValueError):r.alpha_record(copy.deepcopy(p),bad)
        r.alpha_record(p,row);self.assertFalse(p['inStock'])
    def make_kalathi(self):
        p=copy.deepcopy(next(p for p in SEED['products'] if p['source']=='ekalathi'))
        shops={s['id']:s for s in SEED['shops']};rows=[]
        names={'Alphamega':'ΑΛΦΑΜΕΓΑ','Athienitis':'ΑΘΗΑΙΝΙΤΗΣ','Sklavenitis':'ΣΚΛΑΒΕΝΙΤΗΣ','Lidl':'LIDL','Smart Discount Shop':'SMART DISCOUNT SHOP','Wolt Market':'WOLT MARKET'}
        for sid,price in p['prices']:
            s=shops[sid];rows.append({'id':int(sid.split(':')[1]),'name':s['name'],'companyName':names.get(s['retailer'],s['retailer']),'postalAddress':s.get('address'),'retailerProductPrice':price})
        cat={'totalPages':1,'totalElements':1,'content':[{'productMasterId':int(p['sourceProductId']),'name':p['sourceName']}]}
        branch={'totalPages':1,'totalElements':len(rows),'content':rows}
        return {'shops':SEED['shops'],'products':[p]},cat,branch
    def test_kalathi_refresh_preserves_identity(self):
        book,cat,branches=self.make_kalathi();old=book['products'][0]['observedAt'];stats=report()
        r.refresh_kalathi(Fake(cat,branches),book,stats)
        self.assertEqual(stats['updated'],1);self.assertNotEqual(book['products'][0]['observedAt'],old)
    def test_changed_pack_never_gets_fresh_date(self):
        book,cat,branches=self.make_kalathi();old=copy.deepcopy(book);cat['content'][0]['name']+=' 2kg'
        stats=report();r.refresh_kalathi(Fake(cat),book,stats);self.assertEqual(book,old);self.assertEqual(stats['updated'],0)
    def test_changed_address_holds_entire_product_without_redating(self):
        book,cat,branches=self.make_kalathi();old=copy.deepcopy(book);branches['content'][0]['postalAddress']='Different place'
        r.refresh_kalathi(Fake(cat,branches),book,report());self.assertEqual(book,old)
    def test_incomplete_or_duplicate_page_rejected(self):
        for kind in ('truncated','duplicate'):
            book,cat,branches=self.make_kalathi()
            if kind=='truncated':branches['totalElements']+=1
            else:branches['content'][1]=branches['content'][0]
            with self.assertRaises(ValueError):r.refresh_kalathi(Fake(cat,branches),book,report())
    def test_coverage_collapse_keeps_prior_timestamp(self):
        book,cat,branches=self.make_kalathi();old=copy.deepcopy(book);branches['content']=branches['content'][:1];branches['totalElements']=1
        r.refresh_kalathi(Fake(cat,branches),book,report());self.assertEqual(book,old)
    def test_retailer_burgers_not_merged(self):
        book,cat,branches=self.make_kalathi();old=copy.deepcopy(book);branches['content'][0]['companyName']='Different retailer'
        r.refresh_kalathi(Fake(cat,branches),book,report());self.assertEqual(book,old)
    def test_barcode_normalisation(self):
        self.assertEqual(r.barcode('5010026511430'),'05010026511430');self.assertIsNone(r.barcode('5010026511431'))

if __name__=='__main__':unittest.main()

