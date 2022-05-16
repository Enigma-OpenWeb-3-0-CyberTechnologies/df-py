import brownie
from enforce_typing import enforce_types
from pprint import pprint
import pytest

from util import calcrewards, csvs, dispense, query
from util.blockrange import BlockRange
from util.constants import BROWNIE_PROJECT as B
from util.oceanutil import OCEAN_address, recordDeployedContracts
from util.test import conftest

accounts = brownie.network.accounts
chain = brownie.network.chain
CHAINID = 0

@enforce_types
def test_without_csvs(ADDRESS_FILE):
    _setup(ADDRESS_FILE, num_pools=1)

    st, fin, n = 1, len(chain), 5
    rng = BlockRange(st, fin, n)
    OCEAN_avail = 10000.0

    (_, stakes_at_chain, poolvols_at_chain) = query.query(rng, CHAINID)
    rates = {"ocean": 0.5, "h2o": 1.618}

    stakes, poolvols = {CHAINID: stakes_at_chain}, {CHAINID: poolvols_at_chain}
    rewards = calcrewards.calcRewards(stakes, poolvols, rates, OCEAN_avail)
    sum_ = sum(rewards[CHAINID].values())
    assert sum_ == pytest.approx(OCEAN_avail, 0.01), sum_


@enforce_types
def test_with_csvs(ADDRESS_FILE, tmp_path):
    """
    Simulate these steps, with csvs in between
    1. dftool query
    2. dftool getrate
    3. dftool calc
    4. dftool dispense
    """
    _setup(ADDRESS_FILE, num_pools=1)
    csv_dir = str(tmp_path)

    st, fin, n = 1, len(chain), 5
    rng = BlockRange(st, fin, n)

    # 1. simulate "dftool query"
    (_, stakes_at_chain, poolvols_at_chain) = query.query(rng, CHAINID)
    csvs.saveStakesCsv(stakes_at_chain, csv_dir, CHAINID)
    csvs.savePoolvolsCsv(poolvols_at_chain, csv_dir, CHAINID)
    stakes_at_chain = poolvols_at_chain = None  # ensure not used later

    # 2. simulate "dftool getrate"
    csvs.saveRateCsv("OCEAN", 0.25, csv_dir)
    csvs.saveRateCsv("H2O", 1.61, csv_dir)

    # 3. simulate dftool calc"
    stakes = csvs.loadStakesCsvs(csv_dir)
    poolvols = csvs.loadPoolvolsCsvs(csv_dir)
    rates = csvs.loadRateCsvs(csv_dir)
    OCEAN_avail = 10000.0
    rewards = calcrewards.calcRewards(stakes, poolvols, rates, OCEAN_avail)
    sum_ = sum(rewards[CHAINID].values())
    assert sum_ == pytest.approx(OCEAN_avail, 0.01), sum_
    csvs.saveRewardsCsv(rewards, csv_dir, "OCEAN")
    rewards = None  # ensure not used later

    # 4. simulate "dftool dispense"
    rewards = csvs.loadRewardsCsv(csv_dir, "OCEAN")
    token_addr = OCEAN_address()
    dfrewards_addr = B.DFRewards.deploy({"from": accounts[0]}).address
    dispense.dispense(rewards[CHAINID], dfrewards_addr, token_addr, accounts[0])


# ========================================================================
@enforce_types
def _setup(ADDRESS_FILE, num_pools):
    recordDeployedContracts(ADDRESS_FILE, CHAINID)
    conftest.fillAccountsWithOCEAN()
    conftest.randomDeployTokensAndPoolsThenConsume(num_pools)
