# -*-coding: utf-8 -*-
from __future__ import print_function
import sys
from django.db.models.aggregates import Count
if sys.version > '3':
    PY3 = True
else:
    PY3 = False
import csv
from django.conf import settings
from django.views.decorators.http import require_http_methods
from dataset import models
from django.http.response import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json
import requests
import math
from tagging.models import Tag, TaggedItem
from dataset.util import general_json_response, GENERAL_ERRORS
import mygene
from django.core.exceptions import ObjectDoesNotExist
from .util import ComplexEncoder


def adopt_dataset(ds_id):
    if ds_id in settings.DEFAULT_DS_ACCESSION:
        try:
            return models.BiogpsDataset.objects.using('default_dataset')\
                .get(geo_gse_id=ds_id)
        except ObjectDoesNotExist:
            return None

    try:
        return models.BiogpsDataset.objects.get(geo_gse_id=ds_id)
    except ObjectDoesNotExist:
        return None


def get_sample_name_list(ds, from_factor=None):
    names = []
    for f in ds.metadata['factors']:
        if from_factor is not None:
            if from_factor in f[list(f)[0]]['factorvalue']:
                name = f[list(f)[0]]['factorvalue'][from_factor]
            else:
                return []
        else:
            name = list(f)[0]
        names.append(name)
    return names


def get_ds_factors_keys(ds, group=None, collapse=False, naming=None):
    """
        return an array of samples' info(factor value,
         name, display order, color order)
    """
    factors = []
    names = []
    tag = []
    fvs = []
    if group is not None:
        for j, f in enumerate(ds.factors):
            order_idx = color_idx = None
            # exception!
            if group not in f:
                return None
            v = f[group]
            if v not in fvs:
                fvs.append(v)
            color_idx = fvs.index(v)
            if collapse:
                # label(name) switch does not support when collapse is true
                names.append(v)
            # set order just factor value, do real order at the end
            order_idx = v
            factors.append({'order_idx': order_idx, 'color_idx': color_idx})
    else:
        # no group, order by sequence or preset 'order_idx'
        i = 1
        for f in ds.metadata['factors']:
            content = f[list(f)[0]]
            if 'order_idx' in content and 'color_idx' in content:
                order_idx = content['order_idx']
                color_idx = content['color_idx']
            # finally by index number
            else:
                color_idx = order_idx = i
                i = i + 1
            factors.append({'order_idx': order_idx, 'color_idx': color_idx})

    if len(names) == 0:
        names = get_sample_name_list(ds, naming)

    for j, e in enumerate(factors):
        e['name'] = names[j]

    # sort samples by grouped name
    if group:
        fvs.sort()
        t = {}
        interval = len(ds.metadata['factors'])
        for e in factors:
            val = e['order_idx']
            idx = fvs.index(val)
            od = interval*idx
            if not collapse:
                if val in t:
                    t[val] += 1
                    inc = t[val]
                else:
                    inc = t[val] = 0
                od += inc
            e['order_idx'] = od

    return factors


def _contruct_meta(ds):
    preset = {'default': True, 'permission_style': 'public',
              'role_permission': ['biogpsusers'], 'rating_data':
              {'total': 5, 'avg_stars': 10, 'avg': 5}}
    # 'display_params':
    #          {'color': ['color_idx'], 'sort': ['order_idx'],
    #           'aggregate': ['title']}
    if type(ds.metadata['geo_gpl_id']) is dict:
        geo_gpl_id = ds.metadata['geo_gpl_id']['accession']
    else:
        geo_gpl_id = ds.metadata['geo_gpl_id']
    ret = {'id': ds.id, 'name_wrapped': ds.name, 'name': ds.name,
           'owner': ds.ownerprofile_id, 'lastmodified':
           ds.lastmodified.strftime('%Y-%m-%d %H:%M:%S'),
           'pubmed_id': ds.metadata['pubmed_id'], 'summary': ds.summary,
           'geo_gse_id': ds.geo_gse_id, 'created':
           ds.created.strftime('%Y-%m-%d %H:%M:%S'),
           'geo_gpl_id': geo_gpl_id, 'species': [ds.species]
           }
    ret.update(preset)
    return ret


@require_http_methods(["GET"])
def dataset_list(request):
    order = request.GET.get('order', None)
    page = request.GET.get('page', 1)
    page_by = request.GET.get('page_by', 15)
    page = int(page)
    page_by = int(page_by)
    qs = models.BiogpsDataset.objects.all()
    if order == 'pop':
        qs = qs.order_by('-pop_total')
    elif order == 'new':
        qs = qs.order_by('-created')
    else:
        qs = qs.order_by('created')
    count = qs.count()
    total_page = int(math.ceil(float(count) / float(page_by)))
    ret = [{'id': ds.id, 'name': ds.name, 'slug': ds.slug,
            'geo_gse_id': ds.geo_gse_id, 'species': ds.species} for ds in
           qs[(page-1)*page_by: page*page_by]]
#     ds = qs.values_list('id', 'name', 'slug',
#                         'summary')[(page-1)*page_by: page*page_by]
    return general_json_response(detail={"current_page": page,
                                         "total_page": total_page,
                                         "count": count,
                                         "results": ret})


@require_http_methods(["GET"])
def dataset_info(request, ds_id):
    """
        get information about a dataset
    """
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(code=GENERAL_ERRORS.ERROR_NOT_FOUND,
                                     detail="dataset with this id not found")
    ret = _contruct_meta(ds)
    # factors = []
    fa = get_ds_factors_keys(ds)
#     for f in fa:
#         factors.append({f['name']: {"color_idx": f.get('color_idx', 0),
#                         "order_idx": f.get('order_idx', 0), "title": f['name']}
#                         })
#     ret.update({'factors': factors})
    ret.update({'factors': fa})
    return general_json_response(detail=ret)


def _get_reporter_from_gene(gene):
    mg = mygene.MyGeneInfo()
    # res = mg.querymany([gene], scopes='_id', fields='reporter')
    data_json = mg.getgene(gene, fields='reporter')
    if 'reporter' not in data_json:
        return None
    reporters = []
    for i in data_json['reporter'].values():
        if type(i) is not list:
            i = [i]
        reporters = reporters + i
    return reporters


def get_dataset_data(ds, gene_id=None, reporter_id=None):
    """
        get data for dataset
    """
    reporters = []
    if gene_id is not None:
        reporters = _get_reporter_from_gene(gene_id)
        if reporters is None:
            return None
    elif reporter_id is not None:
        reporters.append(reporter_id)
    else:
        return None
    dd = ds.dataset_data.filter(reporter__in=reporters)
    data_list = []
    for d in dd:
        data_list.append({d.reporter: {'values': d.data}})
    return {'id': ds.id, 'name': ds.name, 'data': data_list}


def _avg_with_deviation(li):
    average = round(float(sum(li)) / len(li), 2)
    t = 0
    for e in li:
        total = t + (e - average) ** 2
    dev = round(math.sqrt(float(total) / len(li)), 3)
    return (average, dev)


def prepare_chart_data(val_list, factors):
    """
        combine value and sample info together, grouping, collapse
        by order_index
    """
    import copy
    factors = copy.deepcopy(factors)
    # combine values and samples, just by position in the array
    for idx, e in enumerate(factors):
        e['value'] = val_list[idx]
    factors.sort(key=lambda e: e['order_idx'], reverse=True)
    res = [factors[0]]
    for e in factors[1:]:
        # a new ordered element
        if e['order_idx'] != res[-1]['order_idx']:
            # last element is 'list-value' element
            if type(res[-1]['value']) is list:
                ad = _avg_with_deviation(res[-1]['value'])
                res[-1]['dev'] = ad[1]
                res[-1]['value'] = ad[0]
            else:
                res[-1]['dev'] = 0
            res.append(e)
        # same ordered element, put value to last element together
        else:
            # already have same ordered element
            last_value = res[-1]['value']
            if type(last_value) is list:
                last_value.append(e['value'])
            else:
                res[-1]['value'] = [last_value, e['value']]
    # last element in res
    if type(res[-1]['value']) is list:
        ad = _avg_with_deviation(res[-1]['value'])
        res[-1]['dev'] = ad[1]
        res[-1]['value'] = ad[0]
    else:
        res[-1]['dev'] = 0
    for e in res:
        # remove ' 1' surfix in element name
        if e['name'].endswith(' 1'):
            e['name'] = e['name'][:-2]
    return res


def find_round(v):
    r = math.pow(10, round(math.log(v, 10))*-1+3)
    return 10 if r < 10 else r


def draw_median(ax, pos, length, label):
    ax.plot([pos, pos], [0, length], '#960096', linewidth=0.5)
    ax.text(pos, length, label, ha='center', va='bottom',
            fontsize=7, color='#960096')


def dataset_chart(request, ds_id, reporter_id):
    """
        return a static bar chart for this ds on this reporter
    """
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(GENERAL_ERRORS.ERROR_NOT_FOUND,
                                     "dataset with this id not found.")
    data_list = get_dataset_data(
        ds, reporter_id=reporter_id)['data'][0][reporter_id]['values']
    val_list = [float(item) for item in data_list]

    group = request.GET.get('group', None)
    collapse = request.GET.get('collapse', 'off')
    if collapse == 'on':
        collapse = True
    else:
        collapse = False
    name = request.GET.get('name', None)

    factors = get_ds_factors_keys(ds, group, collapse, name)
    back = prepare_chart_data(val_list, factors)

    # start render part
    import numpy as np
    color_total = len(settings.BAR_COLORS)
    vals, devs, colors, val_dev = [], [], [], []
    for idx, e in enumerate(back):
        vals.append(e['value'])
        devs.append(e['dev'])
        if e['value'] >= 0:
            val_dev.append(e['value']+e['dev'])
        else:
            val_dev.append(e['value']-e['dev'])
        colors.append(settings.BAR_COLORS[e['color_idx'] % color_total])

    y_pos = np.arange(len(back))
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    fig.set_size_inches(15, len(back) * 0.14)
    # draw bars
    # bar width
    width = 0.8
    # only positive error bar
    d_n = []
    d_p = []
    for idx, e in enumerate(vals):
        if e > 0:
            d_n.append(0)
            d_p.append(devs[idx])
        else:
            d_p.append(0)
            d_n.append(devs[idx])
    ax.barh(y_pos, vals, width, color=colors, edgecolor='none',
            xerr=[d_n, d_p], ecolor='#D2691E')
    # eliminate top padding
    plt.axis('tight')
    # x axis range, have some padding space, and take standard dev into account
    li = [max(val_dev), 0, min(val_dev)]
    plt.xlim([min(li)*1.1, max(li)*1.1])

    # x=0, draw y axis
    ax.plot([0, 0], [0, len(back)], 'k', linewidth=0.5)
    # draw median line and label
    # M
    median = np.median(vals)
    rd = find_round(max(vals))
    draw_median(ax, round(median*rd)/rd, len(back),
                'M(%s)' % str(round(median*rd)/rd))
    li = [max(vals), min(vals)]
    # try Mx3
    if median*3 < max(li) and median*3 > min(li):
        draw_median(ax, round(median*3*rd)/rd, len(back), '3xM')
    # try Mx10
    if median*10 < max(li) and median*10 > min(li):
        draw_median(ax, round(median*10*rd)/rd, len(back), '10xM')
    # set ticks attributes
    plt.tick_params(axis='x', which='both', bottom='off', top='off',
                    labelsize=8)
    plt.tick_params(axis='y', which='both', left='on', right='off',
                    direction='out')
    # draw y ticks and label
    ax.set_yticks(y_pos + width / 2)
    ax.set_yticklabels([e['name'] for e in back], fontsize=8)
    # grid on x axis
    plt.gca().xaxis.grid(linestyle='-', color='#aaaaaa')

    response = HttpResponse(content_type='image/png')
    fig.savefig(response, format='png', facecolor='w',
                bbox_inches='tight', pad_inches=0.2)
    return response


def _es_search(rpt, q=None, dft=False, start=0, size=8):
    """
        filter by "default" field and "platform" and query by keywords
        if specified
    """
    body = {"from": start, "size": size}
    # setup filter, filter is faster that query
    body['query'] = {"filtered": {"filter": {"bool": {
        "must": [{"term": {"is_default": dft}},
                 {"has_parent": {"parent_type": "platform", "query":
                                 {"match": {"reporters": rpt}}}}]}}
    }}
    # set query if query word is not None
    if q is not None:
        body["query"]["filtered"]["query"] = {
            "multi_match": {"query": q, "fields": ["summary", "name"]}}

    data = json.dumps(body)
    r = requests.post(settings.ES_URLS['SCH'], data=data)
    return r.json()


@csrf_exempt
def dataset_search(request):
    """
        接受查询的字段组合query和获取的第几页page
    """
    query = request.GET.get("query", None)
    gene = request.GET.get("gene", None)
    page = request.GET.get("page", 1)
    page_by = request.GET.get("page_by", 8)

    if gene is None:
        gene = settings.DEFAULT_GENE_ID
    reporters = _get_reporter_from_gene(gene)
    if reporters is None:
        return general_json_response(
            code=GENERAL_ERRORS.ERROR_NOT_FOUND, detail='no matched\
             data for gene %s.' % gene)
    page = int(page)
    page_by = int(page_by)
    rep = ' '.join(reporters)
    search_res = _es_search(rep, query, False, (page-1)*page_by, page_by)
    count = search_res["hits"]["total"]
    total_page = int(math.ceil(float(count) / float(page_by)))
    res = []
    for e in search_res["hits"]["hits"]:
        _e = e["_source"]
        del _e['summary'], _e['tags']
        res.append(_e)
    res = {"current_page": page, "total_page": total_page, "count": count,
           "results": res}
    return general_json_response(detail=res)


@csrf_exempt
def dataset_search_default(request):
    query = request.GET.get("query", None)
    gene = request.GET.get("gene", None)
    if gene is None:
        gene = settings.DEFAULT_GENE_ID
    reporters = _get_reporter_from_gene(gene)
    if reporters is None:
        return general_json_response(
            code=GENERAL_ERRORS.ERROR_NOT_FOUND, detail='no\
            matched data for gene %s.' % gene)
    # retrive all results
    search_res = _es_search(' '.join(reporters), query, True, 0, 9999)
    res = []
    for e in search_res["hits"]["hits"]:
        _e = e["_source"]
        del _e['summary'], _e['tags']
        res.append(_e)
    res = {"count": len(res),   "results": res}
    return general_json_response(detail=res)


@csrf_exempt
def dataset_search_all(request):
    query = request.GET.get("query", None)
    gene = request.GET.get("gene", None)
    if gene is None:
        gene = settings.DEFAULT_GENE_ID
    reporters = _get_reporter_from_gene(gene)
    if reporters is None:
        return general_json_response(
            code=GENERAL_ERRORS.ERROR_NOT_FOUND, detail='no\
            matched data for gene %s.' % gene)
    # retrive all default results(9999)
    rep = ' '.join(reporters)
    search_res = _es_search(rep, query, True, 0, 9999)
    res_dft = []
    for e in search_res["hits"]["hits"]:
        _e = e["_source"]
        del _e['summary'], _e['tags']
        res_dft.append(_e)
    res_default = {"count": len(res_dft),   "results": res_dft}

    # retrive fist page non-default ds
    page_by = request.GET.get("page_by", 8)
    page_by = int(page_by)
    search_res = _es_search(rep, query, False, 0, page_by)
    count = search_res["hits"]["total"]
    total_page = int(math.ceil(float(count) / float(page_by)))
    res = []
    for e in search_res["hits"]["hits"]:
        _e = e["_source"]
        del _e['summary'], _e['tags']
        res.append(_e)
    res = {"current_page": 1, "total_page": total_page, "count": count,
           "results": res}
    return general_json_response(detail={'default': res_default,
                                         'non-default': res})


def dataset_search_4_biogps(request):
    q = request.GET.get("query", None)
    tag = request.GET.get("tag", None)
    species = request.GET.get("species", None)
    page_by = request.GET.get("page_by", 10)
    page = request.GET.get('page', 1)
    try:
        page_by = int(page_by)
        page = int(page)
    except Exception as e:
        page_by = 10
        page = 1

    filter, query = None, None
    if tag is not None or species is not None:
        filter = {"filter": {"bool": {}}}
        if tag is not None:
            filter["filter"]["bool"].update({"must": {"term": {"tags": tag}}})
        if species is not None:
            filter["filter"]["bool"].update({"must": {"term": {"species": species}}})
    if q is not None:
        query = {"query": {
            "multi_match": {"query": q, "fields": ["summary", "name"]}}}

    if filter is None and query is None:
        return general_json_response(
            code=GENERAL_ERRORS.ERROR_BAD_ARGS, detail='must\
            input a keyword for search or tag or species.')
    else:
        body = {"from": page_by*(page-1), "size": page_by}
        if filter is not None and query is None:
            body.update(filter)
        elif query is not None and filter is None:
            body.update(query)
        else:
            body['query'] = {'filtered':{}}
            body['query']['filtered'].update(filter)
            body['query']['filtered'].update(query)
    data = json.dumps(body)
    r = requests.post(settings.ES_URLS['SCH'], data=data)
    r = r.json()
    hits = []
    count = r["hits"]["total"]
    total_page = int(math.ceil(float(count) / float(page_by)))
    for e in r["hits"]["hits"]:
        _e = e["_source"]
        del _e['summary']
        hits.append(_e)
    res = {"count": count, "current_page": page, "results": hits,
           "total_page": total_page}
    return general_json_response(detail=res)


@require_http_methods(["GET"])
def dataset_info_4_biogps(request, _id):
    """
        get information about a dataset
    """
    ds = models.BiogpsDataset.objects.get(geo_gse_id=_id)
    s = json.dumps(ds, cls=ComplexEncoder)
    oj = json.loads(s)
    del oj['metadata']
    oj['id'] = ds.id
    oj['lastmodified'] = ds.lastmodified.strftime('%b.%d, %Y')
    oj['created'] = ds.created.strftime('%b.%d, %Y')
    oj['summary_wrapped'] = ds.summary_wrapped
    oj['owner'] = ds.metadata['owner']
    if oj['owner'] == "ArrayExpress Uploader":
        oj['sample_source'] = 'http://www.ebi.ac.uk/arrayexpress/experiments/'\
            + oj['geo_gse_id'] + '/samples/'
        oj['source'] = 'http://www.ebi.ac.uk/arrayexpress/experiments/'\
                       + oj['geo_gse_id']
    factors = []
    if oj['factors'] is not None:
        for e in oj['factors']:
            i = oj['factors'].index(e)
            k = list(ds.metadata['factors'][i])[0]
            k = k.rstrip(' 1')
            factors.append({k: e})
    oj['factors'] = factors
#     ret = _contruct_meta(ds)
#     fa = get_ds_factors_keys(ds)
#     ret.update({'factors': ds.factors})
    ts = Tag.objects.get_for_object(ds)
    tags = [t.name for t in ts]
    oj['tags'] = tags
    return general_json_response(detail=oj)


def dataset_csv(request, ds_id, gene_id):
    """
         csv format file download
    """
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(GENERAL_ERRORS.ERROR_NOT_FOUND,
                                     "dataset with this id not found")
    data_list = get_dataset_data(ds, gene_id=gene_id)['data']
    row_list = ['Samples']
    val_list = []
    for item in data_list:
        key_list = list(item)
        for key_item in key_list:
            row_list.append(key_item)
            val_list.append(item[key_item]['values'])
    length = len(val_list[0])
    name_list = get_sample_name_list(ds)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=%s.csv' \
        % ds.geo_gse_id
    writer = csv.writer(response)
    writer.writerow(row_list)
    i = 0
    while(i < length):
        temp_list = []
        if name_list[i].endswith(' 1'):
            name_list[i] = name_list[i][:-2]
        temp_list.append(name_list[i])
        for item in val_list:
            temp_list.append(item[i])
        writer.writerow(temp_list)
        i = i + 1
    return response


@require_http_methods(["GET"])
def dataset_data(request, ds_id, gene_id):
    """
        get information about a dataset
    """
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(detail='dataset with this id not found')
    ret = get_dataset_data(ds, gene_id=gene_id)
    ret['probeset_list'] = ret['data']
    return general_json_response(detail=ret)


@require_http_methods(["GET"])
def dataset_full_data(request, ds_id, gene_id):
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(
            GENERAL_ERRORS.ERROR_BAD_ARGS,
            "Dataset with this id does not exist.")
    data_lists = get_dataset_data(ds, gene_id=gene_id)['data']
    group = request.GET.get('group', None)
    collapse = request.GET.get('collapse', 'off')
    collapse = True if collapse == 'on' else False
    naming = request.GET.get('name', None)
    factors = get_ds_factors_keys(ds, group, collapse, naming)
    res = {}
    for e in data_lists:
        r = list(e)[0]
        vals = [float(item) for item in e[r]['values']]
        back = prepare_chart_data(vals, factors)
        res[r] = back
    ret = _contruct_meta(ds)
    ret.update({'faceted_values': res})
    return general_json_response(detail=ret)


@require_http_methods(["GET"])
def dataset_default(request):
    gene_id = request.GET.get('gene', None)
    if gene_id is None:
        gene_id = settings.DEFAULT_GENE_ID
    mg = mygene.MyGeneInfo()
    res = mg.querymany([gene_id], scopes='_id', fields='taxid')
    data_json = res[0]
    if 'taxid' not in data_json:
        return general_json_response(
            GENERAL_ERRORS.ERROR_BAD_ARGS, "Gene id: %s \
            may be invalid." % gene_id)
    species = data_json['taxid']
    try:
        ds_id = settings.DEFAULT_DATASET_MAPPING[species]
    except IndexError:
        return general_json_response(
            GENERAL_ERRORS.ERROR_BAD_ARGS, "Cannot get default\
            dataset with gene id: %s." % gene_id)
    return general_json_response(detail={'gene': int(gene_id),
                                         'dataset': ds_id})


def calc_correlation(rep, mat, min_corr):
    import numpy as np

    def pearsonr(v, m):
        # Pearson correlation calculation taken from NumPy's implementation
        v_m = v.mean()
        m_m = m.mean(axis=1)
        r_num = ((v - v_m) * (m.transpose() - m_m).transpose()).sum(axis=1)
        r_den = np.sqrt(((v - v_m) ** 2).sum() *
                        (((m.transpose() - m_m).transpose()) ** 2).sum(axis=1))
        r = r_num / r_den
        return r

    rep_pos = mat.reporters.index(rep)
    # Pearson correlations for provided reporter
    if PY3:
        from io import StringIO
    else:
        import StringIO
    matrix_data = np.load(StringIO.StringIO(mat.matrix))
    rep_vector = matrix_data[rep_pos]
    corrs = pearsonr(rep_vector, matrix_data)
    # Get indices of sufficiently correlated reporters
    min_corr = float(min_corr)
    idx_corrs = np.where(corrs > min_corr)[0]
    # Get values for those indices
    val_corrs = corrs.take(idx_corrs)
    # Return highest correlated first
    corrs = zip(val_corrs, idx_corrs)
    corrs.sort(reverse=True)
    rep_cor = {mat.reporters[i[1]]: i[0] for i in corrs}
    # query mygene to get symbol from reporter
    mg = mygene.MyGeneInfo()
    res = mg.querymany(list(rep_cor), scopes='reporter', fields='symbol')
    result = []
    for i in res:
        if 'notfound' in i:
            gene_id, symbol = '', ''
        else:
            gene_id, symbol = i['_id'], i['symbol']
        result.append({'id': gene_id, 'reporter': i['query'],
                       'symbol': symbol, 'value':
                       round(rep_cor[i['query']], 4)})
    return result


def dataset_correlation_usable(request, ds_id):
    ds = adopt_dataset(ds_id)
    if ds.sample_count > settings.MAX_SAMPLE_4_CORRELATION:
        return general_json_response(
            GENERAL_ERRORS.ERROR_INTERNAL, {'sample_count': ds.sample_count})
    try:
        _matrix = models.BiogpsDatasetMatrix.objects.get(dataset=ds)
    except models.BiogpsDatasetMatrix.DoesNotExist:
        return general_json_response(
            GENERAL_ERRORS.ERROR_NOT_FOUND, {'sample_count': ds.sample_count})
    return general_json_response(detail={'sample_count': ds.sample_count})


def dataset_correlation(request, ds_id, reporter_id, min_corr):
    """Return NumPy correlation matrix for provided ID, reporter,
       and correlation coefficient
    """
    ds = adopt_dataset(ds_id)
    if ds.sample_count > settings.MAX_SAMPLE_4_CORRELATION:
        return general_json_response(
            GENERAL_ERRORS.ERROR_INTERNAL, "This dataset contains too many\
             samples (%s) for us to compute pair-wise correlations, \
             so we disabled this feature \
             for this dataset." % ds.sample_count)
    try:
        _matrix = models.BiogpsDatasetMatrix.objects.get(dataset=ds)
    except models.BiogpsDatasetMatrix.DoesNotExist:
        return general_json_response(
            GENERAL_ERRORS.ERROR_NOT_FOUND, "Cannot\
             get matrix of dataset: %s." % ds_id)

    # Get position of reporter
    if reporter_id in _matrix.reporters:
        result = calc_correlation(reporter_id, _matrix, min_corr)
        ret_type = request.GET.get('type', None)
        if ret_type is None:
            return HttpResponse(json.dumps(result, cls=ComplexEncoder),
                                content_type="application/json")
        else:
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename=%s.csv' \
                % ds.geo_gse_id
            writer = csv.writer(response)
            writer.writerow(list(result[0]))
            i = 0
            while(i < len(result)):
                writer.writerow(result[i].values())
                i = i + 1
            return response

    return general_json_response(
        GENERAL_ERRORS.ERROR_BAD_ARGS, "Reporter %s not\
        in dataset: %s." % (reporter_id, ds_id))


def dataset_factors(request, ds_id):
    ds = adopt_dataset(ds_id)
    if ds is None:
        return general_json_response(GENERAL_ERRORS.ERROR_NOT_FOUND,
                                     "dataset with this id not found")
    # no factor value
    if ds.factor_count == 0 or ds.factors is None:
        return general_json_response(code=GENERAL_ERRORS.ERROR_NOT_FOUND)

    factor_keys = {}
    for fv in ds.factors:
        for f in fv:
            if f in list(factor_keys):
                factor_keys[f].add(fv[f])
            else:
                factor_keys[f] = set([fv[f]])
    keys = list(factor_keys)
    for e in keys:
        # remove factors with only 1 options
        if len(factor_keys[e]) == 1:
            del factor_keys[e]
            continue
        factor_keys[e] = list(factor_keys[e])

        # sort, 'not specified' always put last
        # def c(x, y):
        #     if x == 'not specified':
        #         return 1
        #     if y == 'not specified':
        #         return -1
        #     return cmp(x, y)
        factor_keys[e].sort(key=lambda x: x.lower())
        if 'not specified' in factor_keys[e]:
            p = factor_keys[e].index('not specified')
            factor_keys[e].append(factor_keys[e][p])
            del factor_keys[e][p]
    if len(factor_keys) == 0:
        return general_json_response(code=GENERAL_ERRORS.ERROR_NOT_FOUND)
    # dict to array to dicts, then sorting
    ret = []
    for e in factor_keys:
        ret.append({e: factor_keys[e]})

    def c2(x, y):
        kx = x.keys()[0]
        ky = y.keys()[0]
        if kx in settings.POPULAR_FACTORS:
            if ky in settings.POPULAR_FACTORS:
                return cmp(kx, ky)
            else:
                return -1
        else:
            if ky in settings.POPULAR_FACTORS:
                return 1
            else:
                return cmp(kx, ky)
    print(ret)
    ret.sort(key=lambda x: list(x)[0] in settings.POPULAR_FACTORS)
    return general_json_response(detail=ret)


def dataset_tags(request):
    # no factor value
    page = int(request.GET.get("page", 1))
    page_by = int(request.GET.get("page_by", 8))
    count = int(request.GET.get("count", 0))
    from tagging.models import Tag
    qs = Tag.objects.annotate(Count('items')).filter(items__count__gt=count)
    total = qs.count()
    total_page = int(math.ceil(float(total) / float(page_by)))
    li = qs[(page-1)*page_by: page*page_by]
    res = {"current_page": page, "total_page": total_page, "count": total,
           "results": li}
    return general_json_response(detail=res)


def dataset_filter_by_tag(request, tag_name):
    # no factor value
    if tag_name is None:
        return general_json_response(
            GENERAL_ERRORS.ERROR_BAD_ARGS,
            "must input a tag name")
    page = int(request.GET.get("page", 1))
    page_by = int(request.GET.get("page_by", 5))

    qs = TaggedItem.objects.get_by_model(models.BiogpsDataset,
                                         '"%s"' % tag_name)
    total = qs.count()
    total_page = int(math.ceil(float(total) / float(page_by)))
    li = qs[(page-1)*page_by: page*page_by]
    data = []
    for ds in li:
        data.append({"id": ds.id, "name": ds.name, 'geo_gse_id':
                    ds.geo_gse_id, "slug": ds.slug})
    res = {"current_page": page, "total_page": total_page, "count": total,
           "results": data}
    return general_json_response(detail=res)


def dataset_503_test(request):
    """
        just for test 503 error page redirect
    """
    return general_json_response(
        GENERAL_ERRORS.ERROR_NO_PERMISSION,
        "To enable persistent request,\
        add \"X-Email\" HTTP header with your email address")