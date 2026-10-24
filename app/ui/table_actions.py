"""Column sorting over displayed records, without database reloads or row deletion."""


def sort_tree(tree,rows,key,reverse=False,*,value=None):
    """Move existing items only; models retain their original financial values.

    rows maps integer document IDs to current models. An optional value(row)
    supplies a displayed label, e.g. a translated reconciliation status.
    """
    children=list(tree.get_children());x=tree.xview();y=tree.yview()
    def ordered(item):
        row=rows[int(item)];current=value(row) if value else row.get(key)
        return (current is None,current if current is not None else 0) if key.endswith('_minor') else str(current or '').casefold()
    children.sort(key=ordered,reverse=reverse)
    for index,item in enumerate(children):
        tree.move(item,'',index)
        tags=[tag for tag in tree.item(item,'tags') if tag!='alternate']
        if index%2:tags.append('alternate')
        tree.item(item,tags=tags)
    for column in tree['columns']:
        title=tree.heading(column,'text').removesuffix(' ↑').removesuffix(' ↓')
        tree.heading(column,text=title+(' ↓' if reverse else ' ↑') if column==key else title)
    if x:tree.xview_moveto(x[0])
    if y:tree.yview_moveto(y[0])
    return children


def posting_ids(tree,mode):
    """Snapshot stable DB IDs in displayed order; filtering is never selection."""
    try:
        visible=[int(key) for key in tree.get_children()]
        selected={int(key) for key in tree.selection()}
    except (TypeError,ValueError):raise ValueError('Η γραμμή δεν έχει έγκυρο αναγνωριστικό παραστατικού. Κάνε ανανέωση.') from None
    if len(visible)!=len(set(visible)):raise ValueError('Διπλά αναγνωριστικά παραστατικών στην προβολή.')
    if mode=='batch':return visible
    chosen=[key for key in visible if key in selected]
    if mode=='one':
        if len(chosen)!=1:raise ValueError('Επίλεξε ακριβώς ένα παραστατικό.')
        return chosen
    if mode=='selected':return chosen
    raise ValueError('Άγνωστη επιλογή καταχώρισης.')
