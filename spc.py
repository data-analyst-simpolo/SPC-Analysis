import pandas as pd
A2={14:.235};D3={14:.328};D4={14:1.672}
def imr(v):
 s=pd.Series(v,dtype=float).dropna().reset_index(drop=True)
 if len(s)<2:return None
 mr=s.diff().abs().dropna();m=mr.mean();c=s.mean();sig=m/1.128
 return s,c,c+3*sig,c-3*sig,mr,m,3.267*m,0
def xbar_r(f):
 f=pd.DataFrame(f).apply(pd.to_numeric,errors='coerce').dropna();n=f.shape[1]
 if len(f)<2 or n!=14:return None
 means=f.mean(axis=1);ranges=f.max(axis=1)-f.min(axis=1);xb=means.mean();rb=ranges.mean()
 return means,xb,xb+A2[n]*rb,xb-A2[n]*rb,ranges,rb,D4[n]*rb,D3[n]*rb
