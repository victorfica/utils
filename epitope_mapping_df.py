import seaborn as sns
import pandas as pd
import numpy as np
from copy import deepcopy
import argparse
import multiprocessing
import skbio

from fg_shared import *
import itertools
import operator
from functools import partial

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Rectangle

from objhist import objhist

"""Rewrite of epitope_mapping.py that avoids the use of objects,
thereby permitting easy writing/reading of epitope mapping
results to/from files.

response : pd.Series
    A single row from the response DataFrame
    Row is indexed by attributes of the object
island : pd.DataFrame
    A subset of the whole response DataFrame
    containing responses from one PTID that overlap
epitope : pd.Series
    A row from the DataFrame of epitopes
    Has an epitope ID that is specific to the PTID
    Can be merged with the respons DataFrame using the epitopeID"""

# from HLAPredCache import *

import sys
from os.path import join as opj

__all__ = [ 'hamming',
            'overlap',
            'sharedCoords',
            'assignResponseIslands',
            'findEpitopes',
            'identicalRule',
            'overlapRule',
            'hlaRule',
            'findpeptide',
            'plotIsland',
            'encodeVariants',
            'decodeVariants',
            'sliceRespSeq',
            'groupby_parallel',
            'realignPeptides',
            'coord_overlap',
            'plotEpitopeMap',
            'plotEpitopeChiclets',
            'consensusPeptide',
            'alignPeptides',
            'unionCoords',
            'respCoords']

def hamming(str1, str2):
    """Hamming distance between two strings"""
    return sum([i for i in map(operator.__ne__, str1, str2)])

def coord_overlap(start1, end1, start2, end2):
    coords1 = list(range(int(start1), int(end1)))
    coords2 = list(range(int(start2), int(end2)))
    return [i for i in coords1 if i in coords2]

def _coords(r, plot=False):
    """Return coordinates of the response peptide
    Plot option returns coordinates based on start and length of peptide,
    as opposed to end coordinate which is subject to indsertions/deletions
    Use end like a stop in range(start, stop)"""
    if plot:
        return list(range(int(r.start), int(r.start) + len(r.seq)))
    else:
        return list(range(int(r.start), int(r.end)))

def respCoords(r, plot=False):
    """Return coordinates of the response peptide
    Plot option returns coordinates based on start and length of peptide,
    as opposed to end coordinate which is subject to indsertions/deletions
    Use end like a stop in range(start, stop)"""
    if plot:
        return list(range(int(r.start), int(r.start) + len(r.seq)))
    else:
        return list(range(int(r.start), int(r.end)))

def _epcoords(r, plot=False):
    if plot:
        return list(range(int(r.EpStart), int(r.EpStart) + len(r.EpSeq)))
    else:
        return list(range(int(r.EpStart), int(r.EpEnd)))

def overlap(response1, response2):
    """Any overlap between two responses?"""
    if response1.protein == response2.protein:
        coord2 = _coords(response2)
        for i in _coords(response1):
            if i in coord2:
                return True

    return False

def sharedCoords(island):
    """Find the coordinates that are shared by ALL responses in the island"""
    if island.shape[0] > 0:
        sc = set(_coords(island.iloc[0]))
        for ri in range(island.shape[0]):
            response = island.iloc[ri]
            sc.intersection_update(_coords(response))
        return sorted(sc)
    else:
        return []

def unionCoords(island):
    """Find the coordinates that are in ANY of the responses"""
    if island.shape[0] > 0:
        sc = set(_coords(island.iloc[0]))
        for ri in range(island.shape[0]):
            response = island.iloc[ri]
            sc = sc.union(_coords(response))
        return sorted(sc)
    else:
        return []

def alignPeptides(island):
    '''coords = []
    for i,r in island.iterrows():
        coords.extend(_coords(r))
    coords = np.unique(coords)'''
    coords = np.array(unionCoords(island))
    # assert (coords == np.arange(coords[0], coords[-1]+1)).all()

    out = ['-'*(coords < r.start).sum() + r.seq + '-'*(coords > (r.end-1)).sum() for i,r in island.iterrows()]
    return out

def consensusPeptide(island, ignoreGaps=True):
    """Aligns peptides and returns a consensus sequence
    ignoresGaps unless all AA are gaps"""
    align = alignPeptides(island)
    L = len(align[0])

    cons = ''
    for aai in np.arange(L):
        counts = objhist([seq[aai] for seq in align])
        if ignoreGaps and len(counts)>1:
            droppedGaps = counts.pop('-', 0)
        cons += max(list(counts.keys()), key=counts.get)
    return cons

def assignResponseIslands(responses):
    """Return a pd.Series with an island ID that can be joined with
    the responses pd.DataFrame"""
    
    """Contains lists of row indexes of overlapping responses"""
    islandList = []
    for ri in range(responses.shape[0]):
        r = responses.iloc[ri]
        anyFound = False
        for islandi, island in enumerate(islandList):
            """Add the response to each existing island"""
            for islandRespi in island:
                if overlap(r, responses.iloc[islandRespi]):
                    islandList[islandi].append(ri)
                    anyFound = True
                    break
        if not anyFound:
            """Start a new island"""
            islandList.append([ri])
    
    """Return an island column indexed like responses"""
    islandColumn = [''] * responses.shape[0]
    for islandi,island in enumerate(islandList):
        for i in island:
            islandColumn[i] = 'I%d' % islandi
    out = pd.DataFrame({'IslandID': islandColumn})
    out.index = responses.index
    return out

def findEpitopes(responses, sharedRule, reduceResponses=True, returnResponseIndexed=True, **kwargs):
    """Given a list of responses find the minimum
    set of epitopes that "explain" all responses."""

    if reduceResponses:
        """Reduce responses to those with unique start and end positions"""
        coords = {} # keeps track of unique coordinates: (st, en): i
        keepInds = [] # indices we want to keep in the analysis for now
        """Keeps track of redundant coords so we can correctly assign epitopes later"""
        redundantD = {} # key: i, value: list of redundant i's
        for i in range(responses.shape[0]):
            st = responses.start.iloc[i]
            # en = responses.start.iloc[i] + len(responses.seq.iloc[i])
            en = responses.end.iloc[i]
            if not (st, en) in coords:
                coords[(st, en)] = i
                keepInds.append(i)
            else:
                if coords[(st, en)] in redundantD:
                    redundantD[coords[(st, en)]].append(i)
                else:
                    redundantD[coords[(st, en)]] = [i]

        redResp = responses.iloc[keepInds]
    else:
        redResp = responses

    """Start with all possible sets of responses (i.e. combinations)"""
    sharedSets = []
    for N in range(1, redResp.shape[0] + 1):
        for inds in itertools.combinations(list(range(redResp.shape[0])), N):
            sharedSets.append(list(inds))

    """Remove any sets that don't have one unique shared response/epitope"""
    sharedSets = [ss for ss in sharedSets if sharedRule(redResp.iloc[ss], **kwargs)[0]]

    """Remove any sets that are a subset of another set"""
    sharedSetsCopy = deepcopy(sharedSets)
    for s1, s2 in itertools.product(sharedSetsCopy, sharedSetsCopy):
        if (not s1 is s2) and set(s1).issubset(set(s2)):
            try:
                sharedSets.remove(s1)
            except ValueError:
                """It has already been removed"""
                pass

    """Remove any sets whose members are all members of other sets, starting with shorter sets"""
    """Could help remove a few redundant responses, but may not be neccesary if we use the HLA rule"""
    anyRemoved = True
    while anyRemoved:
        anyRemoved = False
        newSharedSets = deepcopy(sharedSets)
        for s1 in sorted(newSharedSets, key=len):
            """For each set of responses"""
            eachExplained = []
            for respInd in s1:
                """For each response index in the set"""
                explained = False
                for s2 in newSharedSets:
                    """For each set of responses"""
                    if (not s2 is s1) and respInd in s2:
                        """If respInd is explained by another, larger set"""
                        explained = True
                eachExplained.append(explained)
            if all(eachExplained):
                sharedSets.remove(s1)
                anyRemoved = True
                """Start for s1 again with updated set of responses"""
                break
    if reduceResponses:
        expSharedSets = []
        for ss in sharedSets:
            tmp = []
            for reducedi in ss:
                i = keepInds[reducedi]
                tmp.append(i)
                if i in redundantD:
                    tmp.extend(redundantD[i])
            expSharedSets.append(tmp)
    else:
        expSharedSets = sharedSets
    if returnResponseIndexed:
        """Return epitope columns indexed like responses
        Deprecated: issue is that response may contain multilpe epitopes
        so index by epitope ID is more natural. Since every epitope has at
        least one response that can only be explained by that epitope,
        the response indexed result is still OK for breadth calc"""
        epitopes = [None] * responses.shape[0]
        for epitopei, inds in enumerate(expSharedSets):
            """Some responses may be in multiple shared sets:
                do not define/restrict epitope location based on these peptides"""
            uinds = []
            for i in inds:
                notUnique = False
                for ssi, ss in enumerate(expSharedSets):
                    if not ssi == epitopei:
                        if i in ss:
                            notUnique = True
                if not notUnique:
                    uinds.append(i)

            ep = sharedRule(responses.iloc[uinds], **kwargs)[1]
            ep['EpID'] = 'E%d' % epitopei
            """This will assign responses an EpID multiple times when it
            could contain either epitope"""
            for i in inds:
                epitopes[i] = ep

        epitopesDf = pd.DataFrame(epitopes)
        epitopesDf.index = responses.index
    else:
        """Return DataFrame that is indexed by epitope and response,
        with potentially more than one epitope per response"""
        epitopes = []
        for epitopei, inds in enumerate(expSharedSets):
            """Some responses may be in multiple shared sets:
                do not define/restrict epitope location based on these peptides"""
            uinds = []
            for i in inds:
                notUnique = False
                for ssi, ss in enumerate(expSharedSets):
                    if not ssi == epitopei:
                        if i in ss:
                            notUnique = True
                if not notUnique:
                    uinds.append(i)

            ep = sharedRule(responses.iloc[uinds], **kwargs)[1]
            ep['EpID'] = 'E%d' % epitopei
            for i in inds:
                tmp = deepcopy(ep)
                tmp['ptid'] = responses['ptid'].iloc[i]
                tmp['IslandID'] = responses['IslandID'].iloc[i]
                tmp['RespID'] = responses['RespID'].iloc[i]
                tmp['Floater'] = 0 if i in uinds else 1
                epitopes.append(tmp)
        epitopesDf = pd.DataFrame(epitopes)
    return epitopesDf

"""
Each rule returns True or False,
    if True it also returns the unique epitope representative of the response island

Simple "shared rule" implementation
(1) Define a rule to determine if a set of responses share a single response in common
    (8 AA overlap, 6 AA matching rule or HLA-based rule)
(2) Begin with all possible sets of responses (including sets of size N, N-1, N-2, ... 1)
(3) Eliminate sets that do not all share a common response
    (i.e. not all pairwise responses share a response)
(4) Eliminate sets that are a subset of another set
(5) Eliminate sets whose members are all members of other sets (starting with shorter sets)
(5) Remaining subsets are the true sets of responses (i.e. breadth)
"""

def identicalRule(island):
    s = set(island.seq)
    if len(s) == 1:
        """If there's just one response"""
        ep = dict(EpSeq=island.iloc[0].seq,
                  EpStart=island.iloc[0].start,
                  EpEnd=island.iloc[0].start + len(island.iloc[0].seq))
        return True, ep
    else:
        return False, {}

def overlapRule(island, minOverlap=8, minSharedAA=6):
    """If all responses share an overlap by at least minOverlap and 
    at least minSharedAA amino acid residues are matched in all responses
    then the responses are considered 'shared'"""
    
    """Find the shared peptide for responses"""
    sharedInds = sharedCoords(island)

    nOverlap = 0
    nMatching = 0
    seq = ''
    for si in sharedInds:
        aas = {respSeq[si - int(respStart)] for respSeq, respStart in zip(island.seq, island.start) if (si - int(respStart)) < len(respSeq)}
        if '-' in aas:
            seq += '-'
        else:
            nOverlap += 1
            if len(aas) == 1:
                nMatching += 1
                seq += aas.pop()
            else:
                seq += 'X'
    if nOverlap >= minOverlap and nMatching >= minSharedAA:
        ep = dict(EpSeq=seq, EpStart=sharedInds[0], EpEnd=sharedInds[-1]+1)
        return True, ep
    else:
        return False, {}

def overlapEpitope(island, useX=True):
    """Find the shared peptide for responses"""
    sharedInds = sharedCoords(island)

    seq = ''
    for si in sharedInds:
        aas = {respSeq[si - int(respStart)] for respSeq, respStart in zip(island.seq, island.start) if (si - int(respStart)) < len(respSeq)}
        if len(aas) == 1:
            seq += aas.pop()
        else:
            if useX:
                seq += 'X'
            else:
                seq += '[' + ''.join(aas) + ']'
                
    return dict(EpSeq=seq, EpStart=sharedInds[0], EpEnd=sharedInds[-1]+1)

def hlaRule(island, hlaList, ba, topPct=0.1, nmer=[8, 9, 10], useX=True):
    """Determine overlap region common amongst all responses in the island
    Predict HLA binding for all mers within the overlap region, for all response sequences (putative epitopes)
    For each mer (defined by start position and length),
        If there is a mer within the topPct for every response then the responses are shared
        Return the mer whose avg rank is best amongst all the responses
    If none of the mers are ranked topPct in all responses then then return None

    TODO: untested and wil need to handle gaps"""
    
    """Find the shared peptide for responses"""
    sharedInds = sharedCoords(island)

    """Indices of all the possible epitopes in the island"""
    possibleEpitopeInds = getMers(sharedInds, nmer=nmer)
    rankPctMat = np.ones((len(island), len(possibleEpitopeInds), len(hlaList)))

    for ri, (rSeq, rL) in enumerate(zip(island.seq, island.L)):
        """Get the predictions for all mers in this response"""
        ranks, sorti, kmers, ic50, hla = rankEpitopes(ba, hlaList, rSeq, nmer=nmer, peptideLength=None)
        for ii, inds in enumerate(possibleEpitopeInds):
            """Find the part of each epitope that overlaps with this response"""
            curMer = ''.join([rSeq[si-rL] for si in inds])
            if len(curMer) in nmer:
                for hi, h in enumerate(hlaList):
                    curIC50 = ba[(h, curMer)]
                    rankPctMat[ri, ii, hi] = (ic50 < curIC50).sum() / len(ic50)

    """Are any of the possible HLA:mer pairs in the topPct for all responses?"""
    if (rankPctMat<=topPct).any(axis=2).any(axis=1).all():
        """Among HLA:mer pairs that are in the topPct, which one is the lowest on avg across responses?"""
        rankPctMat[rankPctMat > topPct] = np.nan
        tmp = np.nanmean(rankPctMat, axis=0)
        avgRank = np.nanmin(tmp)
        ii, hi = np.unravel_index(np.nanargmin(tmp), dims=tmp.shape)
        epitopeInds = possibleEpitopeInds[ii]
        hla = hlaList[hi]

        seq = ''
        for si in epitopeInds:
            aas = {respSeq[si - respStart] for respSeq, respStart in zip(island.seq, island.start)}
            if len(aas) == 1:
                seq += list(aas)[0]
            else:
                if useX:
                    seq += 'X'
                else:
                    seq += '[' + ''.join(aas) + ']'
        ep = dict(EpSeq=seq, EpStart=epitopeInds[0], EpEnd=epitopeInds[-1]+1, hlas=[hla])
        return True, ep
    else:
        return False, {}

def findpeptide(pep, seq, returnGapped=False):
    """Find pep in seq ignoring gaps but returning a start position that counts gaps
    pep must match seq exactly (otherwise you should be using pairwise alignment)

    seq[startPos:endPos] = pep

    Parameters
    ----------
    pep : str
        Peptide to be found in seq.
    seq : str
        Sequence to be searched.
        
    Returns
    -------
    startPos : int
        Start position (zero-indexed) of pep in seq or -1 if not found
    endPos : int
        Stop + 1 position (zero-indexed) of pep in seq or -1 if not found
        Use as stop in range(statr, stop) or slicing [start:stop]"""

    ng = seq.replace('-', '')
    ngInd = ng.find(pep)
    ngCount = 0
    pos = 0
    """Count the number of gaps prior to the non-gapped position.
    Add them to it to get the gapped position"""
    while ngCount < ngInd or seq[pos] == '-':
        if not seq[pos] == '-':
            ngCount += 1
        pos += 1
    startPos = ngInd + (pos - ngCount)

    pepOut = ''
    if startPos == -1:
        endPos = -1
    else:
        count = 0
        endPos = startPos
        while count < len(pep):
            if not seq[endPos] == '-':
                count += 1
                pepOut += seq[endPos]
            else:
                pepOut += '-'
            endPos += 1
    if returnGapped:
        return startPos, endPos, pepOut
    else:
        return startPos, endPos

def sliceRespSeq(r):
    """After the epitope has been identified, slice the response sequence to the appropriate size"""
    start, stop = int(r['EpStart'] - r['start']), int(r['EpStart'] - r['start'] + len(r['EpSeq']))
    
    if 'align seq' in r:
        s = r['align seq']
    else:
        s = r['seq']

    if start < 0 or stop > len(s):
        out = ''
    else:
        out = s[start:stop]
    return out

def encodeVariants(peps):
    """Encode a list of aligned peptides as a single string
    indicating all variants within brackets.

    Example
    -------
    peps = ['KMQKEYALL', 'KKQKEYALL','KMVKEYHAL']
    print(encodeVariants(peps))
    
    'K[MK][QV]KEY[HA][LA]L'
    """
    peps = [p for p in peps if len(p) > 0]
    Ls = np.array([len(s) for s in peps])
    assert np.unique(Ls).shape[0] == 1
    L = Ls[0]
    vs = [list(set([p[i] for p in peps])) for i in range(L)]
    out = ''
    for v in vs:
        if len(v) == 1:
            out += v[0]
        else:
            out += '[' + ''.join(v) + ']'
    return out

def decodeVariants(s):
    """Decode a variant string containing brackets,
    into a list of all possible peptides. Note that
    there are many more decoded variants possible than
    may have been used to generate the variant string.
    (i.e. it is a lossy compression)"""

    vs = []
    inGroup = False
    i = 0
    cur = ''
    while i < len(s):
        if not s[i] in '[]' and inGroup == False:
            vs.append(s[i])
        elif not s[i] in '[]':
            cur += s[i]
        elif s[i] == '[':
            inGroup = True
        elif s[i] == ']':
            inGroup = False
            vs.append(cur)
            cur = ''
        i += 1
    out = [''.join(aas) for aas in itertools.product(*vs)]
    return out

def plotIsland(island):
    """Build an x-vector and AA vector"""
    sitex = []
    immunogens = []
    for i,resp in island.iterrows():
        sitex.extend(_coords(resp, plot=False))
        sitex.extend(_epcoords(resp, plot=False))

    sitex = np.array(sorted(set(sitex)))
    xx = np.arange(len(sitex))
    sitex2xx = {i:j for i, j in zip(sitex, xx)}

    # figh = plt.gcf()
    # figh.clf()
    # axh = figh.add_axes([0.05, 0.05, 0.9, 0.9])
    # axh.patch.set_facecolor('white')

    plt.clf()
    uEpIDs = np.unique(island.EpID)
    colors = {i:c for i,c in zip(uEpIDs, sns.color_palette('Set1', n_colors=uEpIDs.shape[0]))}
    
    ss=[]
    y=1
    for i,r in island.iterrows():
        col = colors[r.EpID]

        plt.plot([sitex2xx[r.start], sitex2xx[r.end - 1]], [y, y], '-s', lw=2, mec='gray', color=col)
        ann = []
        if 'PeptideSet' in r:
            ann.append(r['PeptideSet'])
        if 'align seqs' in r:
            ann.append(r['align seqs'])
        if 'SFC/M' in r:
            ann.append('{:1.0f} SFC/M'.format(r['SFC/M']))
        if 'LANL start' in r and not pd.isnull(r['LANL start']):
            if pd.isnull(r['LANL HLA']):
                s = 'LANL {}'.format(r['LANL Epitope'])
            else:
                s = 'LANL {} {}'.format(r['LANL HLA'], r['LANL Epitope'])
            ann.append(s)

        if len(ann) > 0:
            s = ' | '.join(ann)
            plt.annotate(s,
                         xy=(sitex2xx[r.start], y),
                         xytext=(5, 5),
                         textcoords='offset points',
                         ha='left', va='bottom', size='x-small')
        for xoffset, aa in enumerate(r.seq):
            plt.annotate(aa, xy=(sitex2xx[r.start] + xoffset, y - 0.1), ha='center', va='top', size='small')
        
        """if not hlaList is None and not ba is None:
            ranks,sorti,kmers,ic50,hla=rankKmers(ba,hlaList,r[2],nmer=[8,9,10,11],peptideLength=None)
            rankList=ranks.tolist()
            mers,inds=getMerInds(r[2],nmer=[8,9,10,11])
            notes={}
            for curRank in arange(5):
                curi=where(ranks==curRank)[0][0]
                xcoord=sitex2xx[inds[mers.index(kmers[curi])][0]+r[3]]
                if not notes.has_key(xcoord) or notes[xcoord][1] > ic50[curi]:
                    if AList.issuperset(kmers[curi]):
                        notes.update({xcoord:(hla[curi][:4],ic50[curi],len(kmers[curi]),'%d|A' % (curRank+1))})
                    elif BList.issuperset(kmers[curi]):
                        notes.update({xcoord:(hla[curi][:4],ic50[curi],len(kmers[curi]),'%d|B' % (curRank+1))})
                    else:
                        notes.update({xcoord:(hla[curi][:4],ic50[curi],len(kmers[curi]),'%d' % (curRank+1))})
            for k,v in notes.items():
                annotate('%s\n%1.1f\nL%d\nR%s' % v,
                         xy=(k,y+0.08),
                         xytext=(-1,0),textcoords='offset points',
                         ha='left',va='bottom',size='x-small')"""

        ss += [r.start, r.end - 1]
        y += 1

    y = 0
    for e in uEpIDs[::-1]:
        r = island.loc[island.EpID == e].iloc[0]
        xvec = [sitex2xx[r.EpStart] - 0.3, sitex2xx[r.EpEnd - 1] + 0.3]
        plt.fill_between(xvec, [y, y], island.shape[0], color=colors[e], edgecolor='None', alpha=0.2)
        for xoffset, aa in enumerate(r.EpSeq):
            plt.annotate(aa, xy=(sitex2xx[r.EpStart] + xoffset, y + 0.1),
                         ha='center', va='bottom', size='small', weight='bold')
        ss += [r.EpStart, r.EpEnd - 1]
        y -= 1
    
    plt.yticks([])
    ss = np.unique(ss)
    plt.xlabel('%s coordinate' % r.protein.title(), fontsize='x-large')
    plt.xticks([sitex2xx[sx] for sx in ss], ss.astype(int), size='x-large')
    plt.xlim((-1, len(xx)))
    plt.ylim((-len(uEpIDs), len(island)+1))
    
    handles = [mpl.patches.Patch(facecolor=colors[e], edgecolor='k') for e in uEpIDs]
    plt.legend(handles, uEpIDs, loc='best', title='Epitope')

def plotEpitopeMap(respDf, groupDf, uRespCol, groupCol, startCol, endCol, groupOrder=None, groupColors=None, lw=2):
    """Plot map of all responses in respDf (could be epitopes or 15mers"""
    nPTIDs = groupDf.ptid.unique().shape[0]

    if not groupOrder is None:
        uArms = np.asarray(groupOrder)
    else:
        uArms = groupDf[groupCol].unique()

    tmp = respDf.drop_duplicates(['ptid', uRespCol])[['ptid', uRespCol]]
    breadthDf = tmp.groupby('ptid')[[uRespCol]].count().reset_index()
    breadthDf = pd.merge(groupDf[['ptid', groupCol]].drop_duplicates(), breadthDf, left_on='ptid', right_on='ptid', how='left').fillna(0)

    if groupColors is None:
        groupColors = sns.color_palette('Set1', n_colors=uArms.shape[0])[::-1]

    """Plot map of epitope responses by PTID"""
    plt.clf()
    axh = plt.axes([0.05, 0.1, 0.9, 0.8])
    np.random.seed(110820)
    lasty = 0
    yt = []
    for a, color in zip(uArms[::-1], groupColors[::-1]):
        """Sort PTIDs by breadth"""
        sortedPtids = breadthDf.loc[breadthDf[groupCol] == a].sort_values(by=uRespCol).ptid.tolist()
        # sortedPtids = np.random.permutation(respDf.ptid.unique())
        for y, ptid in enumerate(sortedPtids):
            plotDf = respDf.loc[respDf['ptid'] == ptid].drop_duplicates(subset=['ptid', uRespCol])
            yt.append(y + lasty + 0.5)
            yyvec = np.random.permutation(np.linspace(0, 1, plotDf.shape[0]))
            for yy, st, en in zip(yyvec, plotDf[startCol], plotDf[endCol]):
                plt.plot([st, en], [y + yy + lasty, y + yy + lasty],
                         '-',
                         color=color,
                         linewidth=lw)
        plt.plot([-5, -5], [lasty, lasty + y + 1], '-', color=color, linewidth=7)
        plt.annotate(a,
                     xy=(-5, np.mean([lasty, lasty + y + 1])),
                     xycoords='data',
                     textcoords='offset points',
                     xytext=(-10, 0),
                     ha='right',
                     va='center',
                     rotation=90,
                     size=16, weight='heavy',
                     color='black')
        lasty += y + 3
    if respDf.protein.str.lower().isin(['gp120', 'env', 'gp160']).all():
        keepRegions = ['Signal peptide', 'V1 loop', 'V2 loop',
                       'Loop D', 'V3 loop', 'V4 loop', 'V5 loop', 'gp41']
        reg = pd.read_csv(opj(_git, 'HIV_alignments', 'env_locations.csv'))
        reg = reg.loc[reg.region.isin(keepRegions)]
        reg.loc[:, 'region'] = reg.region.str.replace(' loop', '').str.replace(' ', '\n')
        for i, (region, st, en) in reg.iterrows():
            plt.plot([st, en], [lasty + 1, lasty + 1], 'k-', linewidth=6)
            plt.annotate(region,
                         xy=(st + (en-st)/2., lasty+1),
                         xycoords='data',
                         textcoords='offset points',
                         xytext=(0, 10),
                         ha='center',
                         va='bottom',
                         size='medium',
                         color='black')

    #plt.ylabel('Participants', fontsize=16)
    plt.yticks(yt, ['' for i in range(len(yt))])
    plt.ylim((-1, nPTIDs + 15))

    plt.xlabel('HIV %s HXB2 Position' % respDf.protein.unique()[0])

    #lims = [respDf['start'].min(), (respDf['start'] + respDf['seq'].map(len)).max()]
    lims = [respDf[startCol].min(), respDf[endCol].max()]

    xt = np.arange(0, lims[1] + 50, 50)
    xt[0] += 1
    plt.xticks(xt, xt.astype(int), size=12)
    plt.xlim((-10, lims[1] + 50))
    for s in ['right', 'top', 'left']:
        axh.spines[s].set_visible(False)
    
    handles = [mpl.patches.Patch(facecolor=c, edgecolor='k') for c in groupColors]
    #plt.legend(handles, uArms, loc='upper left', fontsize=15, bbox_to_anchor=[1.02, 1.05])
    #plt.legend(handles, uArms, loc='upper right', fontsize=15)

def plotEpitopeChiclets(respDf, groupDf, uRespCol, groupCol, startCol, endCol,
                        uPTIDs=None, groupOrder=None, groupColors=None, epColorCol=None,
                        chiclet_height=0.6, xtick_width=50, fontsize=16, dropNonresponders=False):
    if uPTIDs is None:
        uPTIDs = groupDf.ptid.unique().tolist()
        nPTIDs = len(uPTIDs)
    else:
        nPTIDs = len(uPTIDs)

    if not groupOrder is None:
        uArms = np.asarray(groupOrder)
    else:
        uArms = groupDf[groupCol].unique()
    
    if groupColors is None:
        groupColors = sns.color_palette('Set1', n_colors=uArms.shape[0])[::-1]

    if epColorCol is None:
        respDf.loc[:, 'EpColor'] = 'None'
    else:
        respDf.loc[:, 'EpColor'] = respDf[epColorCol]

    #lims = [respDf['start'].min(), (respDf['start'] + respDf['seq'].map(len)).max()]
    lims = [respDf[startCol].min(), respDf[endCol].max()]

    tmp = respDf.drop_duplicates(['ptid', uRespCol])[['ptid', uRespCol]]
    breadthDf = tmp.groupby('ptid')[[uRespCol]].count().reset_index()
    if dropNonresponders:
        breadthDf = pd.merge(groupDf[['ptid', groupCol]].drop_duplicates(), breadthDf,
                             left_on='ptid', right_on='ptid', how='right').fillna(0)
    else:
        breadthDf = pd.merge(groupDf[['ptid', groupCol]].drop_duplicates(), breadthDf,
                             left_on='ptid', right_on='ptid', how='left').fillna(0)

    """Plot map of epitope responses by PTID"""
    plt.clf()
    axh = plt.axes([0.05, 0.1, 0.85, 0.8])
    lasty = 0
    yt = []
    for a, color in zip(uArms[::-1], groupColors[::-1]):
        """Sort PTIDs by breadth"""
        sortedPtids = breadthDf.loc[breadthDf[groupCol] == a].sort_values(by=uRespCol).ptid.tolist()
        
        # sortedPtids = np.random.permutation(respDf.ptid.unique())
        for y, ptid in enumerate(sortedPtids):
            plotDf = respDf.loc[respDf['ptid'] == ptid].drop_duplicates(subset=['ptid', uRespCol])
            yt.append(y + lasty)
            rects = []
            for st, en, c in zip(plotDf[startCol], plotDf[endCol], plotDf['EpColor']):
                L = 5
                xloc = np.mean([st, en])
                xy = (xloc - L/2, y + lasty - chiclet_height/2)

                if c == 'None':
                    c = color
                rects.append(Rectangle(xy, width=L, height=chiclet_height, facecolor=c, alpha=1.0, edgecolor='black', lw=0.5))

            # Create patch collection with specified colour/alpha
            pc = PatchCollection(rects, match_original=True)

            # Add collection to axes
            axh.add_collection(pc)

            plt.plot([0, lims[1] + 50], [y + lasty]*2, '-', color='gray', lw=0.5, zorder=-10)
        plt.plot([-5, -5], [lasty, lasty + y + 1], '-', color=color, linewidth=7)
        plt.annotate(a,
                     xy=(-5, np.mean([lasty, lasty + y + 1])),
                     xycoords='data',
                     textcoords='offset points',
                     xytext=(-3, 0),
                     ha='right',
                     va='center',
                     rotation=90,
                     size=fontsize, weight='heavy',
                     color='black')
        lasty += y + 3
    if (respDf.protein.str.lower().isin(['env', 'gp120', 'gp160'])).all():
        keepRegions = ['Signal peptide', 'V1 loop', 'V2 loop',
                       'Loop D', 'V3 loop', 'V4 loop', 'V5 loop', 'gp41']
        reg = pd.read_csv(opj(_git, 'HIV_alignments', 'env_locations.csv'))
        reg = reg.loc[reg.region.isin(keepRegions)]
        reg.loc[:, 'region'] = reg.region.str.replace(' loop', '').str.replace(' ', '\n')
        for i, (region, st, en) in reg.iterrows():
            plt.plot([st, en], [lasty + 1, lasty + 1], 'k-', linewidth=6)
            plt.annotate(region,
                         xy=(st + (en-st)/2., lasty+1),
                         xycoords='data',
                         textcoords='offset points',
                         xytext=(0, 10),
                         ha='center',
                         va='bottom',
                         size=fontsize,
                         color='black')

    # plt.ylabel('Participants', fontsize=16)
    # plt.yticks(yt, ['' for i in range(nPTIDs)])
    plt.yticks(())
    plt.ylim((-1, nPTIDs + 10))
    plt.xlabel('HIV %s HXB2 Position' % respDf.protein.unique()[0], size=fontsize)
    
    xt = np.arange(0, lims[1] + xtick_width, xtick_width)
    xt[0] += 1
    plt.xticks(xt, xt.astype(int), size=fontsize)
    plt.xlim((-10, lims[1] + 50))
    for s in ['right', 'top', 'left']:
        axh.spines[s].set_visible(False)

    handles = [mpl.patches.Patch(facecolor=c, edgecolor='k') for c in groupColors]
    #plt.legend(handles, uArms, loc='upper left', fontsize=15, bbox_to_anchor=[1.02, 0.8])
    #plt.legend(handles, uArms, loc='upper right', fontsize=15)

def AlgnFreeOverlapRule(island, overlapD, minOverlap=7, minSharedAA=5, maxMismatches=3):
    """PROBLEM: Is working partly because it is still dependent on using the shared coords
    Using shared coords greatly reduces complexity of the problem. Will try to go back and
    get correct coords for each peptide

    If all responses share an overlap by at least minOverlap and 
    at least minSharedAA amino acid residues are matched in all responses
    then the responses are considered 'shared'"""
    oParams = dict(overlapD=overlapD,
                   minOverlap=minOverlap,
                   minSharedAA=minSharedAA,
                   maxMismatches=maxMismatches)

    """Find the shared peptide for responses"""
    sharedInds = sharedCoords(island)

    nOverlap = 0
    nMatching = 0
    seq = ''
    for si in sharedInds:
        aas = {respSeq[si - int(respStart)] for respSeq, respStart in zip(island.seq, island.start)}
        if '-' in aas:
            seq += '-'
        else:
            nOverlap += 1
            if len(aas) == 1:
                nMatching += 1
                seq += aas.pop()
            else:
                seq += 'X'
    allOverlap = np.all([isoverlapping(a, b, **oParams) for a,b in itertools.product(island.seq, island.seq)])

    if allOverlap:
    # if nOverlap >= minOverlap and nMatching >= minSharedAA:
        ep = dict(EpSeq=seq, EpStart=sharedInds[0], EpEnd=sharedInds[-1])
        return True, ep
    else:
        return False, {}

def groupby_parallel(gb, func, ncpus=4):
    """Performs a Pandas groupby operation in parallel.
    Example
    -------
    ep = groupby_parallel(posDf.groupby(['ptid', 'IslandID'], .apply(findEpitopes, overlapRule, minSharedAA=5, minOverlap=7))"""
    with multiprocessing.Pool(ncpus) as pool:
        queue = multiprocessing.Manager().Queue()
        result = pool.starmap_async(func, [(name, group) for name, group in gb])
        got = result.get()
    return pd.concat(got)

def realignPeptides(peptides, alignFn, minL=4):
    """Use an alignment to assign peptide locations in alignment coordinates.
    Algorithm first tries to find the whole peptide reporting all sequence IDs
    that match in the alignment. With successive attempts it tries to match kmers
    decreasing lengths with a minimum of minL.

    Parameters
    ----------
    peptides : iterator
        Collection of peptides (e.g. list or pd.Series)
    alignFn : str
        Filename of a FASTA formatted multiple sequence alignment
    minL : None or int
        Value of None requires exact matches be found in the alignment
        or a minimum of minL AAs must match

    Returns
    -------
    resDf : pd.DataFrame shape (len(peptides), 6)
        Columns are: align start, align end, align seq, firstN, lastN, align seqs"""

    seqs = skbio.read(alignFn, format='fasta')
    seqs = {s.metadata['id']:str(s) for s in seqs}
    def _findOne(pep, pos=None, L=None):
        origPep = pep
        if pos is None:
            pos = 0
        if L is None:
            L = len(pep)
        pep = pep[pos:pos + L]

        names = []
        startPos, endPos = -1, -1
        gapped = ''
        for name, s in seqs.items():
            st, en, g = findpeptide(pep, s, returnGapped=True)
            if st >= 0:
                names.append(name)
                startPos, endPos = st, en 
                gapped = g

                core = gapped
                afterCore = origPep[pos + L:]
                beforeCore = origPep[:pos]

                endAdd = len(origPep) - (pos + L)
                add = 0
                afteri = 0
                while add < endAdd:
                    if not s[endPos] == '-':
                        add += 1
                        core = core + afterCore[afteri]
                        afteri += 1
                    else:
                        core = core + '-'
                    endPos += 1

                add = 0
                beforei = 0
                while add < pos:
                    if not s[startPos-1] == '-':
                        add += 1
                        core = beforeCore[pos - beforei - 1] + core
                        beforei += 1
                    else:
                        core = '-' + core
                    startPos -= 1
                """For L < len(origPep) this is filling AAs from the alignment"""
                matched = s[startPos:endPos]
                """while core fills from the original peptide sequence"""

        if startPos == -1:
            pep = ''
            firstN = None
            lastN = None
            matched = ''      
            core = ''
        out = pd.Series({'align start':startPos,
                         'align end':endPos,
                         'align subseq':gapped,
                         'align seq':matched,
                         'realign seq':core,
                         'matched subseq':pep,
                         'seq':origPep,
                         'subpos':pos,
                         'subL':L,
                         'L':len(origPep),
                         'align seqs':'|'.join(names)})
        return out

    resL = []
    for pep in peptides:
        out = _findOne(pep)
        if not minL is None:
            for k in range(len(pep), minL, -1):
                for pos in range(len(pep)-k+1):
                    if out['align start'] < 0:
                        out = _findOne(pep, pos=pos, L=k)
                    else:
                        break
                if out['align start'] > 0:
                    break
        resL.append(out)
    
    outDf = pd.DataFrame(resL)
    if type(peptides) == pd.DataFrame or type(peptides) == pd.Series:
        outDf.index = peptides.index
    colsOrder = ['seq', 'align seq', 'realign seq', 'align subseq',
                 'matched subseq', 'align start', 'align end',
                 'L', 'subL', 'subpos', 'align seqs']
    return outDf[colsOrder]