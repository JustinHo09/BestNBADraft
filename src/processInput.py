import pandas as pd
def main():


def readFile(filename):
    df =[]
    if(filename.endswith(".csv")):
        df = pd.read_csv(filename)
    elif(filename.endswith(".xlsx")):
        df = pd.read_excel(filename)
    else:
        return 'Error Not a supported file type. Must be .csv or .xlsx'

    identities = df.loc[:,2]

    anonymous_stats = df.drop(columns = ['Player'])


