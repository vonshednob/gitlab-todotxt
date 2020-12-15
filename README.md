# gitlab-todotxt

A tool to synchronize GitLab issues to a todo.txt file.

When started, gitlab-todotxt will read the configuration file, load all
issues, and write them into a todo.txt-type file of your choice.


## Configuration

gitlab-todotxt requires a configuration file. It expects the configuration
file by default in ~/.config/gitlab-todotxt/gitlab-todotxt.conf.

Each GitLab configuration is a separate section in the configuration file. The
title of that section must not contain any spaces.

This is an example configuration:

    [example.org]
    url = https://gitlab.example.org
    token = your-access-token
    projects = project1, project2
    unassigned = no


The minimal required options are:

 - `url`, the URL to the GitLab instance you are using.
 - `token`, your personal API access token.
 - `file`, the file where to write the tasks into.

Additional options are:

 - `namespaces`, the list of namespaces to consider when importing issues.
   Only namespaces on this list will be considered when imporrting issues.
   When left empty (the default), all accessible namespaces are considered.
 - `projects`, the list of projects to consider when importing issues. Only
   projects on this list will be considered when importing issues. When left
   empty (the default), all accessible projects are considered.
 - `users`, the list of users to consider when importing issues. Only issues
   that are assigned to a user of this list (or to yourself) are considered
   for importing. When empty (the default) no issues, unless assigned to you,
   are imported.
 - `unassigned`, whether or not unassigned issues should be imported.
 - `labels-are-projects`, whether or not labels of issues should be added as
   project tags.
 - `milestone-prefix`, the prefix you would like to have before the
   `milestone` element, if there is a milestone. Defaults to `milestone:`.
 - `format`, the format to write the todo.txt task in. See below for details.


### Format Option

The `format` option in the configuration can be used to customize in what
form your todo.txt tasks are written to file.

The default is

    {delegate} {title} {due} {project} {milestone} {estimate} {spent} {url}

These are also all possible fields:

 - `delegate`: if an issue is assigned to someone else than you, `@delegated`
   will be written in this place, followed by `to:` and the username of those
   the issue is assigned to
 - `title`: the title of the issue,
 - `due`: the due date of the issue or, if there is none, the due date of the
   milestone this task belongs to (if any); in form of a `due:` tag.
 - `project`: the project this task belongs to.
 - `spent`: the time spent on the task.
 - `estimate`: the estimated time for the task.
 - `milestone`: the milestone of the issue.
 - `url`: the URL to the actual issue at the GitLab website

