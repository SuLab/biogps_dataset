import logging
import os
import json
import pandas


#one data file with all sample data in it
#E-MTAB-1169
class DP_E_GEOD_4006():
    def is_valid(self, data):
        f = data.values()[0]
        f.seek(0)
        header = f.readline().split('\t')
        if 'Scan REF' not in header and 'Hybridization REF' not in header:
            return None
        f.seek(0)
        header[0] = 'REPORTERS'
        df = pandas.read_table(f, names=header, skiprows=2, \
                               index_col=['REPORTERS'])
        return [df]


#one data file with one sample data, might contains junk
#E-GEOD-26688
#E-MEXP-3476
class DP_E_GEOD_15568():
    def is_valid(self, data):
        f = data.values()[0]
        f.seek(0)
        header = f.readline().split('\t')
        if 'ID_REF' not in header and \
          'CompositeSequence Identifier' not in header:
            return None
        df_total = []
        for e in data:
            f = data[e]
            f.seek(0)
            if '_' in e:
                col_name = e.split('_')[0]
            else:
                col_name = e.split('.')[0]
            df = pandas.read_table(f, names=['REPORTERS', col_name],\
              skiprows=1, usecols=['REPORTERS', col_name], \
                index_col=['REPORTERS'])
            df_total.append(df)
        return df_total


class ExperimentDataParse:

    def __init__(self, er, platform):
        self.platform = platform
        self.sdrf = er.sdrf
        self.data = er.data_raw
        self.patterns = [DP_E_GEOD_4006(), DP_E_GEOD_15568()]

    #sort sample sequence in sdrf and data
    #sort reporter sequence in data
    def sort_data_sdrf(self, df):
        sdrf_sorted = []
        df = df.sort_index(axis=1).sort_index(axis=0)
        #sort samples in sdrf by data
        for c in df.columns:
            for e in self.sdrf:
                s = ''.join(e.values())
                if s.find(c) != -1:
                    sdrf_sorted.append(e)
        self.sdrf = sdrf_sorted
        self.data = df

    #experiment may contain multi-platform data, remove
    #sdrf and data that of other platforms, and read left
    #data into pandas matrix
    def filterFormatData(self, dfs):
        #all sample data in one processed file, do sorting
        if len(dfs) == 1:
            self.sort_data_sdrf(dfs[0])
        else:
            #do filter, check if multiple platform user in exp
            dfs_filtered = []
            sdrf_filtered = []
            for d in dfs:
                if len(d.columns) != 1:
                    raise Exception('multipe data files with multiple \
                       columns in it')
                c = d.columns[0]
                for e in self.sdrf:
                    s = ''.join(e.values())
                    if s.find(self.platform) != -1 and s.find(c) != -1:
                        sdrf_filtered.append(e)
                        dfs_filtered.append(d)
            #merge dataframe
            df_total = None
            for d in dfs_filtered:
                if df_total is None:
                    df_total = d
                else:
                    df_total = pandas.merge(df_total, d, left_index=True,\
                                            right_index=True)
            #do sorting
            self.sort_data_sdrf(df_total)

    def parse_data(self):
        dfs = None
        for p in self.patterns:
            dfs = p.is_valid(self.data)
            if dfs is None:
                continue
            else:
                break
        if dfs is None:
            raise Exception('not recognized experiment data')
        return dfs

    def parse(self):
        dfs = self.parse_data()
        self.filterFormatData(dfs)


def check_processed_file_header(header):
    splited = header.split('\t')
    result = {}
    #E-GEOD-4006 style, skp 2 lines
    if splited[0] == 'Scan REF':
        logging.info('2 lines header')
        result['row_skip'] = 2
        result['column_valid'] = len(splited)
    #E-MTAB-1169 style, skp 2 lines
    elif splited[0] == 'Hybridization REF':
        logging.info('2 lines header')
        result['row_skip'] = 2
        result['column_valid'] = len(splited)
    elif splited[0] == 'ID_REF':
        #E-GEOD-26688 style, skip columns after first 2
        if len(splited)>2 and (splited[2] in ['ABS_CALL','4w50nM-3 call']):
            logging.info('1 line header, junk from 3rd column')
            result['row_skip'] = 1
            result['column_valid'] = 2
        #most common cases E-GEOD-15568
        else:
            #logging.info('1 line header')
            result['row_skip'] = 1
            result['column_valid'] = len(splited)
    #E-MEXP-3476 style, skp 2 lines
    elif splited[0] == 'CompositeSequence Identifier':
        logging.info('1 lines header')
        result['row_skip'] = 1
        result['column_valid'] = 2
    else:
        logging.error('can NOT recognize processed data format')
        result['error'] = 'can not recognize processed data format'
    return result



def check_processed(exp, platform):
    result = {'result':True}
    exp_dir = get_exp_dir(exp)
    #header_parsed = False
    column_total = 0
    #header_line = None
    if not os.path.exists(exp_dir):
        logging.error('can NOT find %s'%(exp_dir))
        result['result'] = False
        result['error'] = 'can not locate experiment directory'
        return result
    files = os.listdir('%s%s/'%(exp_dir, platform))
    files.sort()
    for f in files:
        if f.find('processed_') == 0:
            #logging.info('check processed file %s'%f)
            with open('%s%s/%s'%(exp_dir, platform, f), 'r') as file:
                data = file.readline()
                #parse header
                res = check_processed_file_header(data)
                if 'error' in res:
                    result['result'] = False
                    result['error'] = res['error']
                    return result
                column_total = column_total + res['column_valid'] -1
    result.update(res)
    return result


def check_exp_info(exp):
    result = {'result':True}
    exp_dir = get_exp_dir(exp)
    if not os.path.exists(exp_dir):
        logging.error('can NOT find %s'%(exp_dir))
        result['result'] = False
        result['error'] = 'can not locate experiment directory'
        return result
    with open(exp_dir+'experiment', 'r') as file:
        text = file.read()
        parsed = json.loads(text)
        if parsed['experiments']['total'] > 1:
            for e in parsed['experiments']['experiment']:
                if e['accession'] == exp:
                    experiment = e
        else:
            experiment = parsed['experiments']['experiment']
        result['platform'] = []
        #total count of data
        if type(experiment['arraydesign']) is list:
            i = 0
            while i < len(experiment['arraydesign']):
                arraydesign = experiment['arraydesign'][i]
                result['platform'] .append(experiment['arraydesign'][i]['accession'])
                i = i+1
        else:
            result['platform'] = experiment['arraydesign']['accession']
    return result
    

def check_exp(exp, platform=None):
    logging.info('--- check experiment %s ---'%(exp))
    result = {}
    #seems useless now, check experiment
    res = check_exp_info(exp)
    if platform is None:
        if len(res['platform']) > 0:
            logging.info('multiple platforms in the experiment, please specify a platform, then run again.')
            return {'result': False}
        else:
            platform = res['platform'][0]
    result['processed'] = check_processed(exp, platform)
    #if result['exp_info']['result']==True and result['processed']['result']==True:
    if result['processed']['result']==True:
        result['result'] = True
    else:
        result['result'] = False
    logging.info('--- check experiment over ---')
    #print result
    return result
