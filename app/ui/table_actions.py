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
