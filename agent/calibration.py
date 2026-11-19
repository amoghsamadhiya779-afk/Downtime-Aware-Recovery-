""" Phase 3  empirical confidence calibration (CLAUDE.md invariant 5)."""
from __future__ import annotations
from typing import Sequence

class BinnedCalibrator:
    """ Histogram-binning calibrator mapping raw confidence to smooth accuracy."""

    def __init__(self,num_bins: int =10, alpha:float=1.0) ->None:
        if num_bins <1:
            raise ValueError("num_buns must be >=1")
        if alpha <= 0.0:
            raise ValueError("alpha must be >0 for Laplace smoothing ")

        self.num_bins= num_bins
        self.alpha=alpha
        self._bin_probs: list[float]=[]

    def _bin_index(self,raw_conf:float) ->int:
        clamped= min(max(float(raw_conf),0.0),1.0)
        #Clamp p=1.0 into the last bucket (M-1) instead of overlowing to index M.
        return min(int(clamped* self.num_bins),self.num_bins-1)

    def fit(self,raw_confs:Sequence[float],outcomes:Sequence[bool|int |float]) -> BinnedCalibrator:
        """ Bucket -sort samples into M bins and Store Laplace-smoothed empirical accuracy.""" 
        if len(raw_confs) !=len(outcomes) or not raw_confs:
            raise ValueError("raw_confs and outcomes must be non - empty and equal length") 
        counts =[0] * self.num_bins
        hits=[0.0] * self.num_bins
        for conf,y in zip(raw_confs,outcomes):

            idx=self._bin_index(conf)
            counts[idx] +=1          
            hits[idx] += 1.0 if y else 0.0
                
        # Laplace rule of succession avoids 0/0 on empty bins and tempers tiny samples.
        self._bin_probs=[
            (hits[b] +self.alpha)/(counts[b]+2.0*self.alpha)
            for b in range(self.num_bins)

        ]
        return self 
    def calibrate(self,raw_conf:float) ->float:
        """ Map a raw model confidence score to its calibrated bin probability."""
        if not self._bin_probs:
            #Fail closed : never silently echo raw uncalibrated confidence.
            raise RuntimeError("BinnedCalibrator must be fit before calling calibrate()")
        return self._bin_probs[self._bin_index(raw_conf)]        
   
def expected_calibration_error(
        confs:Sequence[float],
        outcomes:Sequence[bool|int|float],
        num_bins:int=10,) -> float:
      """Compute M-bin ECE :sum_b (|B_b| /N)* }acc(B_b) - conf(B_b). """
      if len(confs) != len(outcomes) or not confs:
        raise ValueError("confs and outcomes must be non-empty and equal length")
      if num_bins <1:
        raise ValueError("num_bins must be >=1")  
      counts=[0] *num_bins
      sum_confs=[0.0] * num_bins
      sum_hits=[0.0] * num_bins
      for c,y in zip(confs,outcomes):
        clamped = min(max(float(c), 0.0),1.0)
        b=min(int (clamped*num_bins),num_bins-1)
        counts[b] +=1
        sum_confs[b]+=clamped
        sum_hits[b] +=1.0 if y else 0.0

      n  = len(confs)
      ece =0.0    
      for b in range(num_bins):
        if counts[b]==0:
            continue #Empty bins contribute 0 weight and avoid 0/0
        ece += (counts[b]/n) *abs((sum_hits[b]/counts[b])-(sum_confs[b]/counts[b]))
      return ece  