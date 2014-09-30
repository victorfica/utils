"""
Set of functions that help integrate bootstrap statistical tests into my workflow.

The code is based on chapters from the seminal text:
    Efron B, Tibshirani R. 1993. An introduction to the bootstrapMonographs on statistics and applied probability. Chapman & Hall, New York.

The confidence interval computations is simply a wrapper around the scikits_bootstrap package in pypi:
    scikits-bootstrap (Constantine Evans)
    https://pypi.python.org/pypi/scikits.bootstrap
"""

from __future__ import division
import numpy as np
from scikits_bootstrap import ci

__all__ = ['permTwoSampTest',
           'bootstrapTwoSampTest',
           'bootstrapOneSampTest',
           'bootstrapSE',
           'bootstrapCI',
           'bootstrapPvalue',
           'bootstrapGeneral']

def permTwoSampTest(vec1,vec2,statFunc=None,nPerms=10000):
    """Uses group permutations to calculate a p-value for a
    two sample test for the difference in the mean.
    Optionally specify statFunc for other comparisons."""
    L1=len(vec1)
    L2=len(vec2)
    data=np.concatenate((array(vec1),array(vec2)))
    L=len(data)
    assert L==(L1+L2)

    if statFunc is None:
        statFunc = lambda v1,v2: mean(v1)-mean(v2)

    samples = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = permutation(L)
        samples[sampi] = statFunc(data[inds[:L1]],data[inds[L1:]])
    return (abs(samples)>abs(statFunc(vec1,vec2))).sum()/nPerms

def bootstrapTwoSampTest(vec1,vec2,statFunc=None,nPerms=10000):
    """Uses a bootstrap to calculate a p-value for a
    two sample test for the difference in the mean.
    Optionally specify statFunc for other comparisons."""
    L1=len(vec1)
    L2=len(vec2)
    data=list(vec1)+list(vec2)
    L=len(data)
    assert L==(L1+L2)

    if statFunc is None:
        """Use studentized statistic instead for more accuracy
        (but assumes equal variances)"""
        statFunc = lambda v1,v2: (mean(v1)-mean(v2)) / (sqrt((sum((v1-mean(v1))**2) + sum((v2-mean(v2))**2))/(L1+L2-2)) * sqrt(1/L1+1/L2))
        #statFunc = lambda v1,v2: mean(v1)-mean(v2)

    samples = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = randint(L,size=L)
        samples[sampi] = statFunc([data[i] for i in inds[:L1]],[data[i] for i in inds[L1:]])
    return (abs(samples)>abs(statFunc(vec1,vec2))).sum()/nPerms

def bootstrapPairedTwoSampTest(vec1,vec2,nPerms=10000):
    """Uses a bootstrap to calculate a p-value for a
    two sample paired test of H0: mean(vec1-vec2) != 0"""
    return bootstrapOneSampTest(vec1-vec2,nv=0,nPerms=nPerms)

def bootstrapOneSampTest(data,nv=0,nullTranslation=None,statFunc=None,nPerms=10000):
    """Uses a bootstrap to calculate a p-value for a
    one sample test of H0: mean(data) != nv

    Uses a t-statistic as is used in Efron and Tibshirani"""
    L=len(data)
    if statFunc is None:
        statFunc = lambda data: (np.mean(data)-nv)/(np.std(data)/np.sqrt(len(data)))
        """Could also default to use mean instead of tstat"""
        #statFunc = lambda data: mean(data)-nv
    if nullTranslation is None:
        nullTranslation = lambda data: data - np.mean(data) + nv
    
    nullDist = nullTranslation(data)
    samples = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = randint(L,size=L)
        samples[sampi] = statFunc([nullDist[i] for i in inds])
    return (np.abs(samples)>np.abs(statFunc(data))).sum()/nPerms
def bootstrapPvalue(data,statFunc,alpha=0.05,nPerms=10000,returnNull=False):
    """Uses a bootstrap to compute a pvalue based on the pvalues of a statistic on the data.
    Neccessary for statistics for which it is not easy to specify a null value or translate the
    observed distribution to get a null distribution.
    Good for correlations or paired Wilcoxon tests etc.
    statFunc should return a p-value (uniform distribution for the null)
    Returns the fraction of bootstrap samples for which the pvalue < alpha
    (e.g. rejecting 95% of the bootstrap samples is a global pvalue = 0.05)"""
    L=len(data)
    
    pvalues = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = randint(L,size=L)
        pvalues[sampi] = statFunc([data[i] for i in inds])
    if returnNull:
        return (pvalues>alpha).sum()/nPerms,pvalues
    else:
        return (pvalues>alpha).sum()/nPerms

def bootstrapGeneral(data,nv=0,statFunc=np.mean,nPerms=10000,returnNull=False):
    """Uses a bootstrap to compute a pvalue for a statistic on the data.
    Similar to bootstrapOneSampTest() which is good when the statistic is a mean or tstat.
    This function is good for correlations when nv can be 0
    NOTE: signs might get messed up if nv > obs"""
    L=len(data)
    
    samples = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = randint(L,size=L)
        samples[sampi] = statFunc([data[i] for i in inds])
    if returnNull:
        return 2*(samples<nv).sum()/nPerms,samples
    else:
        return 2*(samples<nv).sum()/nPerms

def bootstrapSE(data,statFunc,nPerms=1000):
    """Bootstrap estimate of the standard error of the specified statistic"""
    L = len(data)
    samples = np.zeros(nPerms)
    for sampi in np.arange(nPerms):
        inds = randint(L,size=L)
        samples[sampi] = statFunc([data[i] for i in inds])
    return samples.std()
def bootstrapCI(data,statFunc=np.mean,alpha=0.05,nPerms=10000,output='lowhigh'):
    """Wrapper around a function in the scikits_bootstrap module:
        https://pypi.python.org/pypi/scikits.bootstrap
    Returns the [alpha/2, 1-alpha/2] percentile confidence intervals
    Use output = 'errorbar' for matplotlib errorbars"""
    try:
        out = ci(data=data,statfunction=statFunc,alpha=alpha,n_samples = nPerms,output=output)
    except IndexError:
        out = [np.nan,np.nan]
    return out