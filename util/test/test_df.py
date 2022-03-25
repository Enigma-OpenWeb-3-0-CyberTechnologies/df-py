#Draws from https://github.com/oceanprotocol/df-js/blob/main/script/index.js

import brownie
import json
import os
from pprint import pprint
import random
import requests
    
from util.base18 import toBase18, fromBase18
from util.constants import BROWNIE_PROJECT, ZERO_ADDRESS
from util import oceanv4util
from util.oceanv4util import calcDID

accounts = brownie.network.accounts

#address file
HOME = os.getenv('HOME')
ADDRESS_FILE = f"{HOME}/.ocean/ocean-contracts/artifacts/address.json"

#subgraph endpoint
SUBGRAPH_URI = "http://127.0.0.1:9000" #barge 
SUBGRAPH_URL = SUBGRAPH_URI + "/subgraphs/name/oceanprotocol/ocean-subgraph"

#pool constants
NUM_POOLS = 2 #3
NUM_STAKERS_PER_POOL = 2 #3
NUM_CONSUMES = 3 #100

AMT_OCEAN_PER_ACCOUNT = 100000.0
AVG_INIT_OCEAN_STAKE = 100.0
AVG_DT_OCEAN_RATE = 1.0
AVG_DT_CAP = 1000.0
AVG_OCEAN_STAKE = 10.0
MAX_OCEAN_IN_BUY = 10000.0
MIN_POOL_BPTS_OUT_FROM_STAKE = 0.1
    
def test_df_endtoend():
    oceanv4util.recordDeployedContracts(ADDRESS_FILE, "development")
    _fillAccountsWithOCEAN()
    _randomDeployAll()

    start_block = 0
    end_block = len(brownie.network.chain)
    rewards = _computeRewards(start_block, end_block)

    _airdropFunds(rewards)

def test_thegraph_approvedTokens():
    oceanv4util.recordDeployedContracts(ADDRESS_FILE, "development")
    OCEAN = oceanv4util.OCEANtoken()

    (DT, pool) = _randomDeployPool(accounts[0])
        
    query = "{ opcs{approvedTokens} }"
    result = _submitQuery(query)

    pprint(result)
    
def test_thegraph_orders():
    oceanv4util.recordDeployedContracts(ADDRESS_FILE, "development")
    OCEAN = oceanv4util.OCEANtoken()

    (DT, pool) = _randomDeployPool(accounts[0])
        
    query = """
        {
          orders(where: {block_gte:0, block_lte:1000, datatoken:%s}, 
                 skip:0, first:5) {
            id,
            datatoken {
              id
            }
            lastPriceToken,
            lastPriceValue
            estimatedUSDValue,
            block
            }
        }
        """ % (DT.address)
    result = _submitQuery(query)

    pprint(result)

#=======================================================================
#COMPUTE REWARDS
def _computeRewards(start_block:int, end_block:int):
    pools = _getAllPools()
    print(f"{len(pools)} pools total")
    
    pools = _filterToApprovedTokens(pools)
    print(f"{len(pools)} pools with approved tokens")

    pools = _filterOutPurgatory(pools)
    print(f"{len(pools)} pools not in purgatory")

    for pool in pools:
        DT_addr = pool["datatoken"]["id"]
        (consume_volume_USDT, consume_volume_OCEAN) = _getConsumeVolume(
            DT_addr, start_block, end_block)
        print(f"Consume volume for DT_addr {DT_addr[:5]}: " \
              f"{consume_volume_USDT} USD, {consume_volume_OCEAN} OCEAN")

def _getConsumeVolume(DT_addr:str, start_block:int, end_block:int) \
    -> (float, float):
    """@return (consume_volume_USDT, consume_volume_OCEAN)"""

    #since we don't know how many orders we have, fetch INC at a time
    # (1000 is max for subgraph)
    consume_volume_USDT = consume_volume_OCEAN = 0.0
    skip = 0
    INC = 5 #FIXME 1000
    while True:
        query = """
        {
          orders(where: {block_gte:%s, block_lte:%s, datatoken:%s}, 
                 skip:%s, first:%s) {
            id,
            datatoken {
              id
            }
            lastPriceToken,
            lastPriceValue
            estimatedUSDValue,
            block
            }
        }
        """ % (start_block, end_block, DT_addr, skip, INC)
        result = _submitQuery(query)
        
        new_orders = result['data']['orders']
        for order in new_orders:
            consume_volume_USDT += float(order["estimatedUSDValue"])
            if (order["lastPriceToken"].lower() == OCEAN.address.lower()):
                consume_volume_OCEAN += float(order["lastPriceValue"])
                
        if not new_orders:
            break
        skip += INC
        
    return (consume_volume_USDT, consume_volume_OCEAN)
    

def _filterOutPurgatory(pools):
    """@return -- pools -- list of dict"""
    bad_dids = _didsInPurgatory()
    return [pool for pool in pools
            if calcDID(pool["datatoken"]["nft"]["id"]) not in bad_dids]

def _didsInPurgatory():
    """return -- list of did (str)"""
    url = "https://raw.githubusercontent.com/oceanprotocol/list-purgatory/main/list-assets.json"
    resp = requests.get(url)

    #list of {'did' : 'did:op:6F7...', 'reason':'..'}
    data = json.loads(resp.text)

    return [item['did'] for item in data]
    
def _filterToApprovedTokens(pools):
    """@return -- pools -- list of dict"""
    approved_tokens = _getApprovedTokens() #list of str of addr
    assert approved_tokens, "no approved tokens"
    return [pool for pool in pools
            if pool['baseToken']['id'] in approved_tokens]

def _getApprovedTokens():
    """@return -- token addresses -- list of str"""
    query = "{ opcs{approvedTokens} }"
    result = _submitQuery(query)
    return result['data']['opcs'][0]['approvedTokens']

def _getAllPools():
    """@return -- pools -- list of dict (pool), where each pool is:
    {
      'id' : '0x..',
      'transactionCount' : '<e.g. 73>',
      'baseToken' : {'id' : '0x..'},
      'dataToken' : {'id' : '0x..', 'nft': {'id' : '0x..'},
    }
    """

    #since we don't know how many pools we have, fetch INC at a time
    # (1000 is max for subgraph)
    pools = []
    skip = 0
    INC = 1000
    while True:
        query = """
        {
          pools(skip:%s, first:%s){
            transactionCount,
            id
            datatoken {
                id,
                nft {
                    id
                }
            },
            baseToken {
                id
            }
          }
        }
        """ % (skip, INC)
        result = _submitQuery(query)
        new_pools = result['data']['pools']
        pools += new_pools
        if not new_pools:
            break
        skip += INC
    return pools
        
def _submitQuery(query: str) -> str:
    request = requests.post(SUBGRAPH_URL,
                            '',
                            json={'query': query})
    if request.status_code != 200:
        raise Exception(f'Query failed. Return code is {request.status_code}\n{query}')

    result = request.json()
    
    return result

#=======================================================================
def _airdropFunds(rewards):
    pass
    
#=======================================================================
#OCEAN
def _fillAccountsWithOCEAN():
    OCEAN = oceanv4util.OCEANtoken()
    
    for i in range(1, 10):
        bal_before = fromBase18(OCEAN.balanceOf(accounts[i]))
        if bal_before < 1000:
            OCEAN.transfer(accounts[i], toBase18(1000), {"from": accounts[0]})
        bal_after = fromBase18(OCEAN.balanceOf(accounts[i]))
        print(f"Account #{i} has {bal_after} OCEAN")
    print(f"Account #0 has {fromBase18(OCEAN.balanceOf(accounts[0]))} OCEAN")


    
#=======================================================================
#DEPLOY STUFF
def _randomDeployAll():
    #create random NUM_POOLS. Randomly add stake.
    tups = [] # (pub_account_i, DT, pool)
    for account_i in range(NUM_POOLS):
        (DT, pool) = _randomDeployPool(accounts[account_i])
        _randomAddStake(pool, account_i)
        tups.append((account_i, DT, pool))

    #consume data assets randomly
    for consume_i in range(NUM_CONSUMES):
        tup = random.choice(tups)
        (pub_account_i, DT, pool) = tup

        #choose consume account
        cand_I = [i for i in range(10) if i != pub_account_i]
        consume_i = random.choice(cand_I)
        consume_account = accounts[consume_i]

        #buy asset
        DT_buy_amt = 1.0
        _buyDT(pool, DT, DT_buy_amt, MAX_OCEAN_IN_BUY, consume_account)

        #consume asset
        pub_account = accounts[pub_account_i]
        _consumeDT(DT, pub_account, consume_account)

def _consumeDT(DT, pub_account, consume_account):
    service_index = 0
    provider_fee = oceanv4util.get_zero_provider_fee_tuple(pub_account)
    consume_mkt_fee = oceanv4util.get_zero_consume_mkt_fee_tuple()
    DT.startOrder(
        consume_account, service_index, provider_fee, consume_mkt_fee,
        {"from": consume_account})

def _randomAddStake(pool, pub_account_i):
    cand_account_I = [i for i in range(10) if i != pub_account_i]
    account_I = random.sample(cand_account_I, NUM_STAKERS_PER_POOL)
    for account_i in account_I:
        OCEAN_stake = AVG_OCEAN_STAKE * (1 + 0.1 * random.random())
        _addStake(pool, OCEAN_stake, accounts[account_i])

def _addStake(pool, OCEAN_stake, from_account):
    OCEAN = oceanv4util.OCEANtoken()
    OCEAN.approve(pool.address, toBase18(OCEAN_stake), {"from": from_account})
    
    token_amt_in = toBase18(OCEAN_stake)
    min_pool_amt_out = toBase18(MIN_POOL_BPTS_OUT_FROM_STAKE) #magic number

    #assert tokenAmountIn <= poolBalanceOfToken * MAX_IN_RATIO, "ERR_MAX_IN_RATIO
    pool.joinswapExternAmountIn(
        token_amt_in, min_pool_amt_out,  {"from": from_account})

def _buyDT(pool, DT, DT_buy_amt: float, max_OCEAN, from_account):
    OCEAN = oceanv4util.OCEANtoken()
    OCEAN.approve(pool.address, toBase18(max_OCEAN), {"from": from_account})

    tokenInOutMarket = [
        OCEAN.address, # token in address
        DT.address,    # token out address
        ZERO_ADDRESS,  # market fee  address
    ]
    amountsInOutMaxFee = [
        toBase18(max_OCEAN),  # max OCEAN in
        toBase18(DT_buy_amt), # target DT out
        toBase18(AVG_DT_OCEAN_RATE*10), # max price
        0,                    # swap market fee
    ]

    #the following test will pass until lotsa activity
    spot_price = fromBase18(pool.getSpotPrice(OCEAN.address, DT.address, 0))
    assert AVG_DT_OCEAN_RATE/5 <= spot_price <= AVG_DT_OCEAN_RATE * 5
    
    #spotPriceBefore = calcSpotPrice(..)
    #assert spotPriceBefore <= (max price)], "ERR_BAD_LIMIT_PRICE"
    pool.swapExactAmountOut(
        tokenInOutMarket, amountsInOutMaxFee, {"from": from_account})
    
def _randomDeployPool(pub_account):
    init_OCEAN_stake = AVG_INIT_OCEAN_STAKE * (1 + 0.1 * random.random())
    DT_OCEAN_rate = AVG_DT_OCEAN_RATE * (1 + 0.1 * random.random())
    DT_cap = int(AVG_DT_CAP * (1 + 0.1 * random.random()))
    return _deployPool(
        init_OCEAN_stake, DT_OCEAN_rate, DT_cap, pub_account)

def _deployPool(init_OCEAN_stake, DT_OCEAN_rate, DT_cap, from_account):
    (data_NFT, erc721_factory) = oceanv4util.createDataNFT(
        "dataNFT", "DATANFTSYMBOL", from_account)

    DT = oceanv4util.createDatatokenFromDataNFT(
        "DT", "DTSYMBOL", DT_cap, data_NFT, from_account)

    pool = oceanv4util.createBPoolFromDatatoken(
        DT,
        erc721_factory,
        from_account,
        init_OCEAN_stake,
        DT_OCEAN_rate,
        DT_vest_amt=0,
    )

    return (DT, pool)

